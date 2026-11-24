import torch
x=torch.arange(10)
print('numel=',x.numel(),'requested=(3,4)')
print(x.reshape(3,4))
