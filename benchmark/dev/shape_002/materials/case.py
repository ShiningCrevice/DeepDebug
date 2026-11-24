import torch
logits = torch.ones(4, 3)
target = torch.tensor([0, 1, 2])
print('logits=(4,3), target=(3,)')
print(torch.nn.functional.cross_entropy(logits, target))
