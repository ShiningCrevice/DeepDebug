outputs = []
with torch.no_grad():
    for batch in loader:
        outputs.append(model(batch.to('cuda')))
