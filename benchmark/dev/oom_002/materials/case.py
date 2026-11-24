loss_total = 0
for batch in loader:
    loss = model(batch).sum()
    loss_total += loss
    loss.backward(retain_graph=True)
