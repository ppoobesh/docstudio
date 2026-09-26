import os
import io
import base64
import zipfile
from flask import Flask, render_template, request, jsonify, send_file
from PIL import Image
from pypdf import PdfWriter, PdfReader

# Explicitly bind base_dir to root project folder
base_dir = os.path.dirname(os.path.abspath(__file__))

app = Flask(
    __name__,
    template_folder=os.path.join(base_dir, 'templates'),
    static_folder=os.path.join(base_dir, 'static')
)

app.config['MAX_CONTENT_LENGTH'] = 50 * 1024 * 1024  # 50MB max body length

def file_to_b64(stream, mime="image/png"):
    return f"data:{mime};base64,{base64.b64encode(stream).decode('utf-8')}"

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/upload', methods=['POST'])
def handle_upload():
    files = request.files.getlist('files')
    cards = []

    for f in files:
        filename = f.filename
        base_name, ext = os.path.splitext(filename)
        ext = ext.lower()
        file_bytes = f.read()

        if ext in ['.jpg', '.jpeg', '.png', '.bmp', '.webp', '.tiff']:
            try:
                img = Image.open(io.BytesIO(file_bytes))
                thumb = img.copy()
                thumb.thumbnail((250, 250))
                buf = io.BytesIO()
                thumb.save(buf, format="PNG")
                
                cards.append({
                    "id": os.urandom(6).hex(),
                    "title": filename,
                    "type": "image",
                    "preview": file_to_b64(buf.getvalue()),
                    "original_data": base64.b64encode(file_bytes).decode('utf-8'),
                    "ext": ext
                })
            except Exception as e:
                print(f"Skipping {filename}: {e}")

        elif ext == '.pdf':
            try:
                reader = PdfReader(io.BytesIO(file_bytes))
                for idx, page in enumerate(reader.pages):
                    card_title = f"{base_name}_{idx + 1}"
                    preview_b64 = None

                    if page.images:
                        try:
                            img_data = page.images[0].data
                            img = Image.open(io.BytesIO(img_data))
                            img.thumbnail((250, 250))
                            buf = io.BytesIO()
                            img.save(buf, format="PNG")
                            preview_b64 = file_to_b64(buf.getvalue())
                        except Exception:
                            pass

                    cards.append({
                        "id": os.urandom(6).hex(),
                        "title": card_title,
                        "type": "pdf_page",
                        "preview": preview_b64,
                        "original_data": base64.b64encode(file_bytes).decode('utf-8'),
                        "page_index": idx
                    })
            except Exception as e:
                print(f"Failed parsing {filename}: {e}")

    return jsonify({"cards": cards})

@app.route('/api/merge', methods=['POST'])
def handle_merge():
    data = request.json or {}
    cards = data.get('cards', [])
    target_kb = data.get('target_kb')
    filename = data.get('filename', 'merged_document.pdf')

    if not filename.endswith('.pdf'):
        filename += '.pdf'

    if not cards:
        return jsonify({"error": "No cards provided"}), 400

    writer = PdfWriter()
    temp_buffers = []

    for c in cards:
        raw_bytes = base64.b64decode(c['original_data'])
        if c['type'] == 'image':
            img = Image.open(io.BytesIO(raw_bytes))
            if img.mode != 'RGB':
                img = img.convert('RGB')
            buf = io.BytesIO()
            img.save(buf, format="PDF", resolution=300)
            buf.seek(0)
            temp_buffers.append(buf)
            writer.add_page(PdfReader(buf).pages[0])

        elif c['type'] == 'pdf_page':
            reader = PdfReader(io.BytesIO(raw_bytes))
            writer.add_page(reader.pages[c['page_index']])

    if target_kb:
        try:
            target_val = float(target_kb)
            quality = 85
            for _ in range(3):
                for page in writer.pages:
                    for img in page.images:
                        img.replace(img.image, quality=quality)
                test_buf = io.BytesIO()
                writer.write(test_buf)
                if (len(test_buf.getvalue()) / 1024) <= target_val or quality <= 25:
                    break
                quality -= 20
        except Exception:
            pass

    out_buf = io.BytesIO()
    writer.write(out_buf)
    out_buf.seek(0)

    for b in temp_buffers:
        b.close()

    return send_file(
        out_buf,
        as_attachment=True,
        download_name=filename,
        mimetype="application/pdf"
    )

@app.route('/api/convert/pdf-to-img', methods=['POST'])
def convert_pdf_to_img():
    cards = request.json.get('cards', [])
    if not cards:
        return jsonify({"error": "No pages selected"}), 400

    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
        for c in cards:
            raw_bytes = base64.b64decode(c['original_data'])
            reader = PdfReader(io.BytesIO(raw_bytes))
            page = reader.pages[c['page_index']]
            
            for img_idx, img in enumerate(page.images):
                img_name = f"{c['title']}.png" if len(page.images) == 1 else f"{c['title']}_{img_idx+1}.png"
                zip_file.writestr(img_name, img.data)

    zip_buffer.seek(0)
    return send_file(zip_buffer, as_attachment=True, download_name="extracted_images.zip", mimetype="application/zip")

@app.route('/api/convert/img-to-pdf', methods=['POST'])
def convert_img_to_pdf():
    cards = request.json.get('cards', [])
    if not cards:
        return jsonify({"error": "No images selected"}), 400

    images = []
    for c in cards:
        raw_bytes = base64.b64decode(c['original_data'])
        im = Image.open(io.BytesIO(raw_bytes))
        if im.mode != 'RGB':
            im = im.convert('RGB')
        images.append(im)

    first = images.pop(0)
    out_buf = io.BytesIO()
    first.save(out_buf, format="PDF", resolution=100.0, save_all=True, append_images=images)
    out_buf.seek(0)

    return send_file(out_buf, as_attachment=True, download_name="converted_images.pdf", mimetype="application/pdf")

@app.route('/api/crop', methods=['POST'])
def handle_crop():
    data = request.json
    raw_bytes = base64.b64decode(data['image_data'])
    coords = data['coords']

    im = Image.open(io.BytesIO(raw_bytes))
    x = int(coords['x'])
    y = int(coords['y'])
    w = int(coords['width'])
    h = int(coords['height'])

    x1 = max(0, x)
    y1 = max(0, y)
    x2 = min(im.width, x1 + w)
    y2 = min(im.height, y1 + h)

    cropped = im.crop((x1, y1, x2, y2))
    out_buf = io.BytesIO()
    cropped.save(out_buf, format="PNG", quality=100)
    out_buf.seek(0)

    return send_file(out_buf, as_attachment=True, download_name="cropped_image.png", mimetype="image/png")

if __name__ == '__main__':
    app.run(debug=True, port=5000)  