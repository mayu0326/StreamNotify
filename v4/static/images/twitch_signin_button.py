# Twitch Sign-In Button SVG Data
# This file will be rendered as a PNG button in the GUI

TWITCH_BUTTON_SVG = '''<svg width="280" height="56" viewBox="0 0 280 56" fill="none" xmlns="http://www.w3.org/2000/svg">
  <rect width="280" height="56" rx="28" fill="#9146FF"/>
  <path d="M32 18L32 38M32 18L42 28L32 38M32 18L22 28L32 38" stroke="white" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
  <text x="60" y="38" font-family="Arial, sans-serif" font-size="18" font-weight="bold" fill="white">Twitch でサインイン</text>
</svg>'''

def create_twitch_button_image():
    """Generate Twitch button image from SVG"""
    from PIL import Image, ImageDraw
    import io

    # Create image
    img = Image.new('RGBA', (280, 56), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Draw rounded rectangle (Twitch purple)
    draw.rounded_rectangle([(0, 0), (279, 55)], radius=28, fill='#9146FF')

    # Draw Twitch logo (simple chat bubble)
    draw.polygon([(32, 18), (42, 28), (32, 38)], outline='white', width=2)

    return img
