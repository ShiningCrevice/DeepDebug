import torch
logits=torch.ones(2,3)
target=torch.tensor([0,4])
print('logits=(2,3), targets=[0,4]')
print(torch.nn.functional.cross_entropy(logits,target))
