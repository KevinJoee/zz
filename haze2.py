"""
Like image_sample.py, but use a noisy image classifier to guide the sampling
process towards more realistic images.
"""

import argparse
import os

import numpy as np
import torch as th
import torch.distributed as dist
import torch.nn.functional as F

# from guided_diffusion import dist_util, logger
from guided_diffusion import logger
from guided_diffusion.script_util_x0_enhancement import (
    NUM_CLASSES,
    model_and_diffusion_defaults,
    create_model_and_diffusion,
    create_model_and_diffusion_direct,
    add_dict_to_argparser,
    args_to_dict,
)

from save_image_utils import save_images
from npz_dataset import NpzDataset, DummyDataset
from imagenet_dataloader.imagenet_dataset import ImageFolderDataset

import torchvision.transforms as transforms
from PIL import Image,ImageFilter
import cv2
import pdb
import random
import math
import torch
import torch.nn as nn

import MyLoss
import time 

os.environ['CUDA_VISIBLE_DEVICES']='0'

def get_dataset(path, global_rank, world_size):
    if os.path.isfile(path): # base_samples could be store in a .npz file
        dataset = NpzDataset(path, rank=global_rank, world_size=world_size)
    else:
        dataset = ImageFolderDataset(path, label_file='./imagenet_dataloader/imagenet_val_labels.pkl', transform=None, 
                        permute=True, normalize=True, rank=global_rank, world_size=world_size)
    return dataset

# degradation model
deg = 'sr4'
image_size = 256
channels = 3
device = 'cuda:0'
H_funcs = None
if deg[:3] == 'inp':
    from functions.svd_replacement import Inpainting
    if deg == 'inp_lolcat':
        loaded = np.load("inp_masks/lolcat_extra.npy")
        mask = torch.from_numpy(loaded).to(device).reshape(-1)
        missing_r = torch.nonzero(mask == 0).long().reshape(-1) * 3
    elif deg == 'inp_lorem':
        loaded = np.load("inp_masks/lorem3.npy")
        mask = torch.from_numpy(loaded).to(device).reshape(-1)
        missing_r = torch.nonzero(mask == 0).long().reshape(-1) * 3
    else:
        loaded = np.loadtxt("/nvme/feiben/DDPM_Beat_GAN/scripts/imagenet_dataloader/inp_masks/mask.np")
        mask = torch.from_numpy(loaded).to(device)
        missing_r = mask[:image_size**2 // 4].to(device).long() * 3  
    missing_g = missing_r + 1
    missing_b = missing_g + 1
    missing = torch.cat([missing_r, missing_g, missing_b], dim=0)
    H_funcs = Inpainting(channels, image_size, missing, device)
elif deg[:2] == 'sr':
    blur_by = int(deg[2:])
    from functions.svd_replacement import SuperResolution
    H_funcs = SuperResolution(channels, image_size, blur_by, device)
else:
    print("ERROR: degradation type not supported")
    quit()


def main():
    args = create_argparser().parse_args()
    os.environ['CUDA_VISIBLE_DEVICES'] = str(args.device)
    device = th.device('cuda')
    save_dir = args.save_dir if len(args.save_dir)>0 else None

    # dist_util.setup_dist()
    logger.configure(dir = save_dir)

    logger.log("creating model and diffusion...")
    model, diffusion = create_model_and_diffusion_direct(
        **args_to_dict(args, model_and_diffusion_defaults().keys())
    )

    model.load_state_dict(
        th.load(args.model_path, map_location="cpu")
    )
    # model.to(dist_util.dev())
    model.to(device)
    if args.use_fp16:
        model.convert_to_fp16()
    model.eval()

    L_exp = MyLoss.L_exp(8,0.4)
    L_color = MyLoss.L_color()
    L_DC = MyLoss.DCLoss()

    def light_cond_fn(x, t, corner=None, y=None, x_lr=None, sample_noisy_x_lr=False, diffusion=None, sample_noisy_x_lr_t_thred=None):
        assert y is not None
        # assert light_factor is not None
        with th.enable_grad():
            x_in = x.detach().requires_grad_(True)
            loss = 0
            x_lr0=x_lr
            x_lr0=x_lr0.to(device)
            if not x_lr is None:
                # x_lr and x_in are of shape BChw, BCHW, they are float type that range from -1 to 1, x_in for small t'
                x_lr = x_lr[:, :, corner[0]:corner[0]+corner[2], corner[1]:corner[1]+corner[2]]
                device_x_in_lr = x_in.device
                # x_in_lr = x_in
                x_in_tmp = H_funcs.H(((x_in+1)/2).to(th.float32))
                x_in_lr = H_funcs.H_pinv(x_in_tmp).view(x_in_tmp.shape[0], 3, 256, 256)
                if deg[:6] == 'deblur': x_in_lr = x_in_tmp.view(x_in_tmp.shape[0], 3, 256, 256)
                elif deg == 'color': x_in_lr = x_in_tmp.view(x_in_tmp.shape[0], 1, image_size, image_size).repeat(1, 3, 1, 1)
                x_in_lr.to(th.uint8)
                # x_in.to(th.uint8)

                if sample_noisy_x_lr:
                    t_numpy = t.detach().cpu().numpy()
                    spaced_t_steps = [diffusion.timestep_reverse_map[t_step] for t_step in t_numpy]
                    if sample_noisy_x_lr_t_thred is None or spaced_t_steps[0] < sample_noisy_x_lr_t_thred:
                        print('Sampling noisy lr')
                        spaced_t_steps = th.Tensor(spaced_t_steps).to(t.device).to(t.dtype)
                        x_lr = diffusion.q_sample(x_lr, spaced_t_steps)

                x_lr = x_lr.to(device_x_in_lr)
                x_lr = (x_lr + 1) / 2
                x_in1 = (x_in + 1) / 2
                mse = (x_in - x_lr) ** 2
                mse = mse.mean(dim=(1,2,3))
                mse = mse.sum()
                loss_exp = torch.mean(L_exp(x_in))
                loss_col = torch.mean(L_color(x_in))
                loss_dc = (L_DC(x_in, 35))
                # Loss_TV = L_TV(light_mask)
                # loss = loss - mse * args.img_guidance_scale - loss_exp * args.img_guidance_scale / 100 - loss_col * args.img_guidance_scale /200  - Loss_TV * args.img_guidance_scale # move xt toward the gradient direction
                # loss = loss - loss_exp *args.img_guidance_scale/ 100 #- loss_col * args.img_guidance_scale /200- loss_dc* args.img_guidance_scale/600
                loss = loss - loss_exp * args.img_guidance_scale /10#loss_exp *args.img_guidance_scale/ 100 #- loss_col * args.img_guidance_scale /200- loss_dc* args.img_guidance_scale/600
                # light_factor = light_factor - th.autograd.grad(mse, light_factor,retain_graph=True)[0]
                # light_mask = light_mask - th.autograd.grad(mse, light_mask,retain_graph=True)[0]
                print('step t %d img guidance has been used, mse is %.8f * %d = %.2f' % (t[0], mse, args.img_guidance_scale, mse*args.img_guidance_scale))
            return th.autograd.grad(loss, x_in)[0], x_lr0


    def model_fn(x, t, y=None):
        assert y is not None
        # assert light_factor is not None
        return model(x, t, y if args.class_cond else None)

    logger.log("loading dataset...")
    # load gan or vae generated images
    if args.start_from_scratch and args.use_img_for_guidance:
        pass
    else:
        if args.start_from_scratch:
            dataset = DummyDataset(args.num_samples, rank=args.global_rank, world_size=args.world_size)
        else:
            dataset = get_dataset(args.dataset_path, args.global_rank, args.world_size)
        dataloader = th.utils.data.DataLoader(dataset, batch_size=args.batch_size, shuffle=False, num_workers=16)

    # load lr images that are used for guidance 
    if args.use_img_for_guidance:
        dataset_lr = get_dataset(args.base_samples, args.global_rank, args.world_size)     
        dataloader_lr = th.utils.data.DataLoader(dataset_lr, batch_size=args.batch_size, shuffle=False, num_workers=16)  

        if args.start_from_scratch:
            dataset = DummyDataset(len(dataset_lr), rank=0, world_size=1)
            dataloader = th.utils.data.DataLoader(dataset, batch_size=args.batch_size, shuffle=False, num_workers=16)
        dataloader = zip(dataloader, dataloader_lr)

    # args.save_png_files=True
    if args.save_png_files:
        print(logger.get_dir())
        os.makedirs(os.path.join(logger.get_dir(), 'images'), exist_ok=True)
        os.makedirs(os.path.join(logger.get_dir(), 'mask'), exist_ok=True)
        os.makedirs(os.path.join(logger.get_dir(), 'gt'), exist_ok=True)
        os.makedirs(os.path.join(logger.get_dir(), 'lr'), exist_ok=True)
        start_idx = args.global_rank * dataset.num_samples_per_rank

    logger.log("sampling...")
    all_images = []
    all_labels = []
    # while len(all_images) * args.batch_size < args.num_samples:
    for i, data in enumerate(dataloader):
        if args.use_img_for_guidance:
            image, label = data[0]
            image_lr, label = data[1]
            cond_fn = lambda x,t,corner,y : light_cond_fn(x, t, corner=corner, y=y, x_lr=image_lr, sample_noisy_x_lr=args.sample_noisy_x_lr, diffusion=diffusion, sample_noisy_x_lr_t_thred=args.sample_noisy_x_lr_t_thred)
        else:
            image, label = data
            cond_fn = lambda x,t,y : general_cond_fn(x, t, y=y, x_lr=None)
        if args.start_from_scratch:
            shape = (image.shape[0], 3, 400, 600)
        else:
            shape = list(image.shape)
        if args.start_from_scratch and not args.use_img_for_guidance:
            classes = th.randint(low=0, high=NUM_CLASSES, size=(shape[0],), device=device)
        else:
            classes = label.to(device).long()

        image = image.to(device)
        model_kwargs = {}
        # model_kwargs["image_lr"] = image_lr
        model_kwargs["y"] = classes
        sample_fn = (
            diffusion.p_sample_loop if not args.use_ddim else diffusion.ddim_sample_loop
        )

        if args.start_from_scratch:
            sample = sample_fn(
                model_fn,
                shape,
                # light_factor, 
                # light_mask,
                clip_denoised=args.clip_denoised,
                model_kwargs=model_kwargs,
                cond_fn=cond_fn,
                device=device
            )
        else:
            sample = sample_fn(
                model_fn,
                shape,
                clip_denoised=args.clip_denoised,
                model_kwargs=model_kwargs,
                cond_fn=cond_fn,
                device=device,
                noise=image,
                denoise_steps=args.denoise_steps
            )

        sample = ((sample + 1) * 127.5).clamp(0, 255).to(th.uint8)
        sample = sample.permute(0, 2, 3, 1)
        sample = sample.contiguous()

        image_lr = ((image_lr + 1) * 127.5).clamp(0, 255).to(th.uint8)
        image_lr = image_lr.permute(0, 2, 3, 1)
        image_lr = image_lr.contiguous()

        # light_mask = ((light_mask + 1) * 127.5).clamp(0, 255).to(th.uint8)
        # light_mask = light_mask.unsqueeze(0).unsqueeze(0).repeat(1,3,1,1).permute(0, 2, 3, 1)
        # light_mask = light_mask.contiguous()

        # light_mask = light_mask.detach().cpu().numpy()
        sample = sample.detach().cpu().numpy()
        classes = classes.detach().cpu().numpy()
        image_lr = image_lr.detach().cpu().numpy()
        if args.save_png_files:
            save_images(sample, classes, start_idx + len(all_images) * args.batch_size, os.path.join(logger.get_dir(), 'images'))

            # save_images(light_mask, classes, start_idx + len(all_images) * args.batch_size, os.path.join(logger.get_dir(), 'mask'))

            save_images(image_lr, classes, start_idx + len(all_images) * args.batch_size, os.path.join(logger.get_dir(), 'lr'))
        all_images.append(sample)
        all_labels.append(classes)
        logger.log(f"created {len(all_images) * args.batch_size} samples")

    # dist.barrier()
    logger.log("sampling complete")


def create_argparser():
    defaults = dict(
        clip_denoised=True,
        num_samples=100,
        batch_size=1,
        use_ddim=False,
        model_path="/home/qyj/GDP/ckpt/256x256_diffusion_uncond.pt",
    )
    defaults.update(model_and_diffusion_defaults())
    parser = argparse.ArgumentParser()
    add_dict_to_argparser(parser, defaults)
    
    # save_dir  = os.path.join('/home/qyj/GDP/save', ('generated_image_x0_GDP_' + deg))
    save_dir  = os.path.join('/home/qyj/GDP/save', ('generated_image_x0_GDP_water'))
    # base_samples  = os.path.join('/nvme/feiben/DDPM_Beat_GAN/scripts/imagenet_dataloader', (deg + ('_resolution_256.npz')))
    # add zhaoyang own's arguments
    parser.add_argument("--device", default=0, type=int, help='the cuda device to use to generate images')
    parser.add_argument("--global_rank", default=0, type=int, help='global rank of this process')
    parser.add_argument("--world_size", default=1, type=int, help='the total number of ranks')
    parser.add_argument("--save_dir", default=save_dir, type=str, help='the directory to save the generate images')
    parser.add_argument("--save_png_files", action='store_true', help='whether to save the generate images into individual png files')
    parser.add_argument("--save_numpy_array", action='store_true', help='whether to save the generate images into a single numpy array')
    
    # these two arguments are only valid when not start from scratch
    parser.add_argument("--denoise_steps", default=25, type=int, help='number of denoise steps')
    parser.add_argument("--dataset_path", default='/home/qyj/GDP/data/high', type=str, help='path to the generated images. Could be an npz file or an image folder')
    
    parser.add_argument("--use_img_for_guidance", action='store_true', help='whether to use a (low resolution) image for guidance. If true, we generate an image that is similar to the low resolution image')
    parser.add_argument("--img_guidance_scale", default=6000, type=float, help='guidance scale')
    parser.add_argument("--base_samples", default='/home/qyj/GDP/data/low', type=str, help='the directory or npz file to the guidance imgs. This folder should have the same structure as dataset_path, there should be a one to one mapping between images in them')
    parser.add_argument("--sample_noisy_x_lr", action='store_true', help='whether to first sample a noisy x_lr, then use it for guidance. ')
    parser.add_argument("--sample_noisy_x_lr_t_thred", default=1e8, type=int, help='only for t lower than sample_noisy_x_lr_t_thred, we add noise to lr')
    
    parser.add_argument("--start_from_scratch", action='store_true', help='whether to generate images purely from scratch, not use gan or vae generated samples')
    parser.add_argument("--deg", default='sr4', type=str, help='the chosen of degradation model')
    # num_samples is defined elsewhere, num_samples is only valid when start_from_scratch and not use img as guidance
    # if use img as guidance, num_samples will be set to num of guidance images
    # parser.add_argument("--num_samples", type=int, default=50000, help='num of samples to generate, only valid when start_from_scratch is true')
    return parser

import pdb
if __name__ == "__main__":
    main()
