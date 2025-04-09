from PIL import Image

# Open the PNG file
with Image.open(r"C:\Users\anike\Downloads\New folder\Aadhaar front.png") as im:
    # Convert image to RGB mode (JPEG does not support transparency)
    rgb_im = im.convert("RGB")
    # Save the image in JPEG format
    rgb_im.save(r"C:\Users\anike\Downloads\New folder\Aadhaar front.jpg", "JPEG")

with Image.open(r"C:\Users\anike\Downloads\New folder\Aadhaar back.png") as im:
    # Convert image to RGB mode (JPEG does not support transparency)
    rgb_im = im.convert("RGB")
    # Save the image in JPEG format
    rgb_im.save(r"C:\Users\anike\Downloads\New folder\Aadhaar back.jpg", "JPEG")