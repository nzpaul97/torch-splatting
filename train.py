import torch
import numpy as np
import gaussian_splatting.utils as utils
from gaussian_splatting.trainer import Trainer
import gaussian_splatting.utils.loss_utils as loss_utils
from gaussian_splatting.utils.data_utils import read_all
from gaussian_splatting.utils.camera_utils import to_viewpoint_camera
from gaussian_splatting.utils.point_utils import get_point_clouds
from gaussian_splatting.gauss_model import GaussModel
from gaussian_splatting.gauss_render import GaussRenderer
import habana_frameworks.torch.core as htcore
import habana_frameworks.torch.gpu_migration
import time

import contextlib

from torch.profiler import profile, ProfilerActivity, record_function

import os
os.environ['LOG_LEVEL_PT_FALLBACK'] = "1"

USE_GPU_PYTORCH = True
USE_PROFILE = False

class GSSTrainer(Trainer):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.data = kwargs.get('data')
        self.gaussRender = GaussRenderer(**kwargs.get('render_kwargs', {}))
        self.lambda_dssim = 0.2
        self.lambda_depth = 0.0
        self.previous_output = torch.empty(0)
    
    def on_train_step(self):
        valid_idx = [1, 2, 3, 4, 5, 6, 8, 9, 10, 11, 13, 14, 17, 19 ]
        # ind = np.random.choice(len(self.data['camera']))
        ind = np.random.choice(len(valid_idx))
        ind = valid_idx[ind]
        print("index is : ", ind)
        camera = self.data['camera'][ind]
        rgb = self.data['rgb'][ind]
        depth = self.data['depth'][ind]
        mask = (self.data['alpha'][ind] > 0.5)
        if USE_GPU_PYTORCH:
            camera = to_viewpoint_camera(camera)

        if USE_PROFILE:
            activities = [torch.profiler.ProfilerActivity.CPU]
            activities.append(torch.profiler.ProfilerActivity.HPU)

            # prof = profile(activities=[ProfilerActivity.CUDA], with_stack=True)

            prof = profile(
                # schedule=torch.profiler.schedule(wait=0, warmup=20, active=5, repeat=1),
                activities=activities,
                record_shapes=True,
                on_trace_ready=torch.profiler.tensorboard_trace_handler('./profile_logs'),
                profile_memory=True,
                with_stack=True)
        else:
            prof = contextlib.nullcontext()

        with prof:
            out = self.gaussRender(pc=self.model, camera=camera)

        if USE_PROFILE:
            print(prof.key_averages(group_by_stack_n=True).table(sort_by='self_cuda_time_total', row_limit=20))

        # # Print parameter gradients
        # print("Gradients:")
        # for name, param in self.model.named_parameters():
        #     if param.grad is not None:
        #         print(f"{name}: {param.grad.max}")
        #     else:
        #         print(f"{name}: No gradient calculated")
        #     # print(name, tensor.shape)
        
        print("output of renderer : ", out["render"][200][200].tolist())
        if self.previous_output.numel() == 0:
            self.previous_output = out['render'].clone()
        comparison = torch.eq(self.previous_output, out['render'])
        print("num of matched outputs : ", torch.sum(comparison).item())
        self.previous_output = out['render']

        l1_loss = loss_utils.l1_loss(out['render'], rgb)
        depth_loss = loss_utils.l1_loss(out['depth'][..., 0][mask], depth[mask])
        ssim_loss = 1.0-loss_utils.ssim(out['render'], rgb)

        total_loss = (1-self.lambda_dssim) * l1_loss # + self.lambda_dssim * ssim_loss + depth_loss * self.lambda_depth
        psnr = utils.img2psnr(out['render'], rgb)
        log_dict = {'total': total_loss,'l1':l1_loss, 'ssim': ssim_loss, 'depth': depth_loss, 'psnr': psnr}

        print("l1 loss : ", l1_loss.item())

        return total_loss, log_dict

    def on_evaluate_step(self, **kwargs):
        import matplotlib.pyplot as plt
        ind = np.random.choice(len(self.data['camera']))
        camera = self.data['camera'][ind]
        if USE_GPU_PYTORCH:
            camera = to_viewpoint_camera(camera)

        rgb = self.data['rgb'][ind].detach().cpu().numpy()
        out = self.gaussRender(pc=self.model, camera=camera)
        rgb_pd = out['render'].detach().cpu().numpy()
        depth_pd = out['depth'].detach().cpu().numpy()[..., 0]
        depth = self.data['depth'][ind].detach().cpu().numpy()
        depth = np.concatenate([depth, depth_pd], axis=1)
        depth = (1 - depth / depth.max())
        depth = plt.get_cmap('jet')(depth)[..., :3]
        image = np.concatenate([rgb, rgb_pd], axis=1)
        image = np.concatenate([image, depth], axis=0)
        utils.imwrite(str(self.results_folder / f'image-{self.step}.png'), image)

    def track_grad(self):
        pc = self.model
        print("tracking grad of 100th pc: ", pc._xyz.grad[100].tolist())


if __name__ == "__main__":
    iter_start = time.time()
    # iter_end = torch.cuda.Event(enable_timing = True)

    # iter_start.record()

    device = 'hpu'
    folder = './B075X65R3X'
    data = read_all(folder, resize_factor=0.5)
    data = {k: v.to(device) for k, v in data.items()}
    data['depth_range'] = torch.Tensor([[1,3]]*len(data['rgb'])).to(device)


    points = get_point_clouds(data['camera'], data['depth'], data['alpha'], data['rgb'])
    raw_points = points.random_sample(2**14)
    # raw_points.write_ply(open('points.ply', 'wb'))

    gaussModel = GaussModel(sh_degree=4, debug=False, device="hpu")
    gaussModel.create_from_pcd(pcd=raw_points)
    
    render_kwargs = {
        'white_bkgd': True,
        'device':'hpu',
    }

    trainer = GSSTrainer(model=gaussModel, 
        data=data,
        train_batch_size=1, 
        train_num_steps=25000,
        i_image =100,
        train_lr=1e-3, 
        amp=False,
        fp16=False,
        results_folder='result/test122601',
        render_kwargs=render_kwargs,
    )

    trainer.on_evaluate_step()
    trainer.train()

    iter_end = time.time()

    print(iter_end-iter_start)