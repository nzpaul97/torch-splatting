# torch-splatting
A pure pytorch implementation of 3D gaussian splatting. 

## Train
clone the repo

```bash
git clone https://github.com/hbb1/torch-splatting.git --recursive
```

and run

```bash
python train.py
```


Tile-based rendering is implemeted. Because running loop for python is slow, it uses 64x64-sized tile instead of 16x16 as 3DGSS did. The training time is about 2 hours for 512x512 resolution image for 30k iterartions, tested on a RTX 3090 and cpu. The number of 3D gaussians is fixed, of 16384 points. Under this setting, it matchs the original diff-gaussian-splatting implementation on RTX 3090

Still does not work properly on GAUDI V2


## Reference

https://github.com/graphdeco-inria/gaussian-splatting/tree/main

https://github.com/graphdeco-inria/diff-gaussian-rasterization

https://github.com/openai/point-e/tree/main/point_e
