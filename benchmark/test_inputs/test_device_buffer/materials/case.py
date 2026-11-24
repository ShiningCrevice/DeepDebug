import torch
class Model(torch.nn.Module):
    def __init__(self):
        super().__init__()
        self.offset = torch.ones(4)
    def forward(self, x):
        return x + self.offset
m = Model().to('cuda:0')
x = torch.ones(2,4,device='cuda:0')
print('offset=', m.offset.device, 'input=', x.device)
print(m(x))
