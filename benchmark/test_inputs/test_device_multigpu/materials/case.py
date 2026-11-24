left = left_branch(x.to('cuda:0'))
right = right_branch(x.to('cuda:1'))
merged = left + right
