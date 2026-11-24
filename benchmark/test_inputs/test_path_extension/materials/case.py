from pathlib import Path
Path('model.pth').write_text('demo')
print('existing=model.pth requested=model.pt')
print(Path('model.pt').read_bytes())
