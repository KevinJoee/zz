# This repository contains PyTorch implementation.
For installing, follow these intructions:

    conda create -n pytorch python=3.8<br />
    conda activate pytorch<br />
    conda install pytorch==1.8.0 torchvision==0.9.0 torchaudio==0.8.0 cudatoolkit=11.1 -c pytorch -c conda-forge<br />
    pip install matplotlib scikit-image opencv-python yacs joblib natsort h5py tqdm kornia tensorboard ptflops<br />

Before runing, please download the pre-trained DDPM model. Here are the download links for each model checkpoint:

        64x64 classifier: 64x64_classifier.pt<br />
        64x64 diffusion: 64x64_diffusion.pt<br />
        128x128 classifier: 128x128_classifier.pt<br />
        128x128 diffusion: 128x128_diffusion.pt<br />
        256x256 classifier: 256x256_classifier.pt<br />
        256x256 diffusion: 256x256_diffusion.pt<br />
        256x256 diffusion (not class conditional): 256x256_diffusion_uncond.pt<br />
        512x512 classifier: 512x512_classifier.pt<br />
        512x512 diffusion: 512x512_diffusion.pt<br />
        64x64 -> 256x256 upsampler: 64_256_upsampler.pt<br />
        128x128 -> 512x512 upsampler: 128_512_upsampler.pt<br />

Train and Test:<br />

        python train.py <br />
        For more details, see [guided-diffusion](https://github.com/openai/guided-diffusion)

Results: <br />
![image](https://github.com/user-attachments/assets/d0f2b17b-8ffb-46b8-a5e5-25cada06d9d8)
![image](https://github.com/user-attachments/assets/ae63cd2a-7720-418c-ac69-737f82f4baa4)


