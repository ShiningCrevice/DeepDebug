optimizer = torch.optim.AdamW(model.parameters())
loss.backward()
optimizer.step()
