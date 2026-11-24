import torch
x = torch.ones(4, 4, device='cuda:0')
bias = torch.eye(4)
print('x=', x.device, 'bias=', bias.device)
print(x + bias)
