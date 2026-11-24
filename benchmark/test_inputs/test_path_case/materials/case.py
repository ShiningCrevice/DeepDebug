from pathlib import Path
Path('Model.json').write_text('{}')
print('existing=Model.json requested=model.json')
print(Path('model.json').read_text())
