import requests
from PIL import Image, ImageEnhance, ImageOps, ImageFilter
from io import BytesIO
import os
import logging
import hashlib
import tempfile
import subprocess
import platform
import shutil
from pathlib import Path

logger = logging.getLogger(__name__)

_SWIFTSHADER_ARCHITECTURES = {"x86_64", "amd64", "i386", "i686"}
_CHROMIUM_EXECUTABLES = [
    "chromium-browser",
    "chromium",
    "google-chrome",
    "google-chrome-stable",
    "chromium-headless-shell"
]


def _get_gl_flag():
    arch = platform.machine().lower()
    if arch in _SWIFTSHADER_ARCHITECTURES:
        return "--use-gl=swiftshader"
    return "--use-gl=egl"


def _normalize_target(target: str) -> str:
    if target.startswith(("http://", "https://", "file://")):
        return target
    if os.path.exists(target):
        return Path(target).resolve().as_uri()
    return target


def _build_chromium_command(executable, target, img_file_path, dimensions):
    gl_flag = _get_gl_flag()
    base_flags = [
        "--headless",
        f"--screenshot={img_file_path}",
        f"--window-size={dimensions[0]},{dimensions[1]}",
        "--disable-dev-shm-usage",
        "--disable-gpu",
        gl_flag,
        "--hide-scrollbars",
        "--in-process-gpu",
        "--js-flags=--jitless",
        "--disable-zero-copy",
        "--disable-gpu-memory-buffer-compositor-resources",
        "--disable-extensions",
        "--disable-plugins",
        "--mute-audio",
        "--no-sandbox"
    ]

    if executable == "chromium-headless-shell":
        return [executable, target, *base_flags]
    return [executable, *base_flags, target]

def get_image(image_url):
    response = requests.get(image_url)
    img = None
    if 200 <= response.status_code < 300 or response.status_code == 304:
        img = Image.open(BytesIO(response.content))
    else:
        logger.error(f"Received non-200 response from {image_url}: status_code: {response.status_code}")
    return img

def change_orientation(image, orientation, inverted=False):
    if orientation == 'horizontal':
        angle = 0
    elif orientation == 'vertical':
        angle = 90

    if inverted:
        angle = (angle + 180) % 360

    return image.rotate(angle, expand=1)

def resize_image(image, desired_size, image_settings=[]):
    img_width, img_height = image.size
    desired_width, desired_height = desired_size
    desired_width, desired_height = int(desired_width), int(desired_height)

    img_ratio = img_width / img_height
    desired_ratio = desired_width / desired_height

    keep_width = "keep-width" in image_settings

    x_offset, y_offset = 0,0
    new_width, new_height = img_width,img_height
    # Step 1: Determine crop dimensions
    desired_ratio = desired_width / desired_height
    if img_ratio > desired_ratio:
        # Image is wider than desired aspect ratio
        new_width = int(img_height * desired_ratio)
        if not keep_width:
            x_offset = (img_width - new_width) // 2
    else:
        # Image is taller than desired aspect ratio
        new_height = int(img_width / desired_ratio)
        if not keep_width:
            y_offset = (img_height - new_height) // 2

    # Step 2: Crop the image
    image = image.crop((x_offset, y_offset, x_offset + new_width, y_offset + new_height))

    # Step 3: Resize to the exact desired dimensions (if necessary)
    return image.resize((desired_width, desired_height), Image.LANCZOS)

def apply_image_enhancement(img, image_settings={}):

    # Apply Brightness
    img = ImageEnhance.Brightness(img).enhance(image_settings.get("brightness", 1.0))

    # Apply Contrast
    img = ImageEnhance.Contrast(img).enhance(image_settings.get("contrast", 1.0))

    # Apply Saturation (Color)
    img = ImageEnhance.Color(img).enhance(image_settings.get("saturation", 1.0))

    # Apply Sharpness
    img = ImageEnhance.Sharpness(img).enhance(image_settings.get("sharpness", 1.0))

    return img

def compute_image_hash(image):
    """Compute SHA-256 hash of an image."""
    if image is None:
        raise ValueError("Cannot compute hash of an empty image")
    image = image.convert("RGB")
    img_bytes = image.tobytes()
    return hashlib.sha256(img_bytes).hexdigest()

def take_screenshot_html(html_str, dimensions, timeout_ms=None):
    image = None
    try:
        # Create a temporary HTML file
        with tempfile.NamedTemporaryFile(suffix=".html", delete=False) as html_file:
            html_file.write(html_str.encode("utf-8"))
            html_file_path = html_file.name

        image = take_screenshot(html_file_path, dimensions, timeout_ms)

        # Remove html file
        os.remove(html_file_path)

    except Exception as e:
        logger.error(f"Failed to take screenshot: {str(e)}")

    return image

def take_screenshot(target, dimensions, timeout_ms=None):
    image = None
    img_file_path = None
    try:
        # Create a temporary output file for the screenshot
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as img_file:
            img_file_path = img_file.name

        normalized_target = _normalize_target(target)
        timeout_seconds = (timeout_ms / 1000.0) if timeout_ms else None

        errors = []
        screenshot_taken = False
        for executable in _CHROMIUM_EXECUTABLES:
            if shutil.which(executable) is None:
                continue

            command = _build_chromium_command(executable, normalized_target, img_file_path, dimensions)
            run_kwargs = {"stdout": subprocess.PIPE, "stderr": subprocess.PIPE}
            if timeout_seconds:
                run_kwargs["timeout"] = timeout_seconds

            try:
                result = subprocess.run(command, **run_kwargs)
            except subprocess.TimeoutExpired:
                message = f"{executable} timed out after {timeout_seconds} seconds"
                errors.append(message)
                logger.error(message)
                continue
            except Exception as exc:
                message = f"{executable} failed: {exc}"
                errors.append(message)
                logger.error(message)
                continue

            if result.returncode == 0 and os.path.exists(img_file_path):
                screenshot_taken = True
                break

            # Skip executables that fail with SIGILL (illegal instruction, often due to architecture mismatch)
            if result.returncode == 132:
                continue

            stderr_output = result.stderr.decode('utf-8', errors='replace')
            message = f"{executable} exited with code {result.returncode}: {stderr_output.strip()}"
            errors.append(message)
            logger.error(message)

        if not screenshot_taken:
            if not errors:
                logger.error("Failed to take screenshot: No chromium executable found")
            else:
                logger.error("Failed to take screenshot:")
                for err in errors:
                    logger.error(err)
            return None

        # Load the image using PIL
        with Image.open(img_file_path) as img:
            image = img.copy()

    except Exception as e:
        logger.error(f"Failed to take screenshot: {str(e)}")
    finally:
        if img_file_path and os.path.exists(img_file_path):
            os.remove(img_file_path)

    return image

def pad_image_blur(img: Image, dimensions: tuple[int, int]) -> Image:
    bkg = ImageOps.fit(img, dimensions)
    bkg = bkg.filter(ImageFilter.BoxBlur(8))
    img = ImageOps.contain(img, dimensions)

    img_size = img.size
    bkg.paste(img, ((dimensions[0] - img_size[0]) // 2, (dimensions[1] - img_size[1]) // 2))
    return bkg
