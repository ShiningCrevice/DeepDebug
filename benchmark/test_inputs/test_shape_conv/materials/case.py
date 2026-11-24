import torch
m=torch.nn.Conv2d(3,4,3)
x=torch.ones(2,1,8,8)
print('input_shape=',tuple(x.shape),'in_channels=',m.in_channels)
print(m(x))
