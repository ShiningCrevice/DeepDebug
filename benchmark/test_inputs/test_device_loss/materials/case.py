import torch
logits = torch.ones(2,3,device='cuda:0')
target = torch.tensor([0,1],device='cuda:0')
weight = torch.ones(3)
print('logits=',logits.device,'target=',target.device,'weight=',weight.device)
print(torch.nn.functional.cross_entropy(logits,target,weight=weight))
