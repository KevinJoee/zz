## This repository contains PyTorch implementation for Learning Physical-aware Diffusion Priors for Zero-shot Restoration of Scattering-affected Images
## For installing, follow these intructions:

    conda create -n pytorch python=3.8  
    conda activate pytorch  
    conda install pytorch==1.8.0 torchvision==0.9.0 torchaudio==0.8.0 cudatoolkit=11. -c pytorch -c conda-forge  
    pip install matplotlib scikit-image opencv-python numpy blobfile tqdm pyYaml pillow tensorboard 

## Before runing, please download the pre-trained DDPM model. Here are the download links for each model checkpoint:

        64x64 classifier: 64x64_classifier.pt  
        64x64 diffusion: 64x64_diffusion.pt  
        128x128 classifier: 128x128_classifier.pt  
        128x128 diffusion: 128x128_diffusion.pt  
        256x256 classifier: 256x256_classifier.pt  
        256x256 diffusion: 256x256_diffusion.pt  
        256x256 diffusion (not class conditional): 256x256_diffusion_uncond.pt  
        512x512 classifier: 512x512_classifier.pt  
        512x512 diffusion: 512x512_diffusion.pt  
        64x64 -> 256x256 upsampler: 64_256_upsampler.pt  
        128x128 -> 512x512 upsampler: 128_512_upsampler.pt

## Datesets
        Please download the dataset for the corresponding task  
        For example, the underwater image dataset can be downloaded from here https://drive.google.com/file/d/1Ew_r83nXzVk0hlkfuomWqsAIxuq6kaN4/view

## Train and Test:  

        python train.py  
        
        For more details, see [guided-diffusion](https://github.com/openai/guided-diffusion)

## Results:  
![image](https://github.com/user-attachments/assets/ae63cd2a-7720-418c-ac69-737f82f4baa4)  


