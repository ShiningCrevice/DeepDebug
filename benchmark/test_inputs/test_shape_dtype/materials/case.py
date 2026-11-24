import torch
m=torch.nn.Linear(4,2)
x=torch.ones(2,4,dtype=torch.int64)
print('input_dtype=',x.dtype,'weight_dtype=',m.weight.dtype)
print(m(x))
