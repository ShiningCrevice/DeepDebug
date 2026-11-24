import torch
m = torch.nn.Linear(4,2).to('cuda:0')
m.weight = torch.nn.Parameter(torch.ones(2,4))
x = torch.ones(2,4,device='cuda:0')
print('weight=',m.weight.device,'input=',x.device)
print(m(x))
