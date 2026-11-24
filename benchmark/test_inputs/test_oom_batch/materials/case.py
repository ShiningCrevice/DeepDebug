batch_size = config['batch_size']
x = torch.ones(batch_size, 3, 2048, 2048, device='cuda')
features = encoder(x)
