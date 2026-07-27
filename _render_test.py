"""Render Virgo Desktop to PNG to verify layout."""
import sys, os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
sys.path.insert(0, os.path.dirname(__file__))

from PyQt6.QtCore import QPoint
from PyQt6.QtGui import QPixmap, QPainter, QColor
from PyQt6.QtWidgets import QApplication

app = QApplication(sys.argv)

from virgo_desktop import VirgoDesktopWindow
w = VirgoDesktopWindow()
w.show()
app.processEvents()

# Wait briefly for layout
import time
time.sleep(0.5)
app.processEvents()

# Render to PNG
pm = QPixmap(w.size())
pm.fill(QColor('#1e1e2e'))
p = QPainter(pm)
w.render(p, QPoint(0, 0))
p.end()
pm.save('_virgo_render.png')

# Check content
from PIL import Image
img = Image.open('_virgo_render.png')
px = img.load()
non_bg = 0
for x in range(0, img.width, 5):
    for y in range(0, img.height, 5):
        r, g, b = px[x, y][:3]
        if (r, g, b) != (30, 30, 46):
            non_bg += 1

print(f'Render: {img.width}x{img.height}')
print(f'Non-bg pixels: {non_bg}')
if non_bg < 100:
    print('WARNING: Almost no content rendered!')
else:
    print('Content IS rendering in offscreen mode.')
print(f'Saved to _virgo_render.png — open it to see what the app should look like.')
