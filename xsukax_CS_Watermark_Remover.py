#!/usr/bin/env python3
"""
xsukax CamScanner PDF Watermark Remover

Removes CamScanner watermarks and exports to PDF/PNG/TIF
Created by: xsukax


Usage:
    python watermark_remover.py input.pdf
    python watermark_remover.py input.pdf --format pdf
    python watermark_remover.py input.pdf --format png --dpi 300
    python watermark_remover.py input.pdf --format tif

Requirements:
    pip install pikepdf PyMuPDF Pillow
"""

import sys
import os
import re
import time
from pathlib import Path
from io import BytesIO
from contextlib import contextmanager

try:
    import pikepdf
    from pikepdf import Pdf, Name, Array, Dictionary
except ImportError:
    print("❌ pikepdf not installed. Run: pip install pikepdf")
    sys.exit(1)

try:
    import fitz
except ImportError:
    print("❌ PyMuPDF not installed. Run: pip install PyMuPDF")
    sys.exit(1)

try:
    from PIL import Image
except ImportError:
    print("❌ Pillow not installed. Run: pip install Pillow")
    sys.exit(1)


class Config:
    BRAND = "xsukax CamScanner PDF Watermark Remover"
    MAIN_CONTENT_THRESHOLD = 1000
    DEFAULT_DPI = 300
    
    WATERMARK_KEYWORDS = [
        'camscanner', 'CamScanner', 'CAMSCANNER',
        'intsig', 'Intsig', 'INTSIG',
        'www.camscanner.com', 'camscanner.com',
        'intsig.net', 'intsig.com',
        'Scanned with CamScanner'
    ]
    
    WATERMARK_URLS = ['camscanner.com', 'intsig.net', 'intsig.com']


class XsukaxRemover:
    
    def __init__(self, debug=False, export_format='pdf', dpi=300):
        self.debug = debug
        self.export_format = export_format.lower()
        self.dpi = dpi
        self.config = Config()
        self.stats = {
            'pages': 0,
            'annotations': 0,
            'images': 0,
            'text_blocks': 0,
            'metadata': 0
        }
    
    @contextmanager
    def suppress_stderr(self):
        """Suppress stderr output temporarily"""
        stderr = sys.stderr
        try:
            sys.stderr = open(os.devnull, 'w')
            yield
        finally:
            sys.stderr.close()
            sys.stderr = stderr
    
    def log(self, msg, level='INFO'):
        icons = {'INFO': 'ℹ', 'SUCCESS': '✓', 'ACTION': '→', 'DEBUG': '🔍', 'ERROR': '✗', 'WARNING': '⚠'}
        if level == 'DEBUG' and not self.debug:
            return
        icon = icons.get(level, '•')
        print(f"[{icon}] {msg}")
    
    def print_header(self):
        print("\n" + "═" * 70)
        print(f"  {self.config.BRAND}")
        print("═" * 70)
    
    def print_summary(self):
        total = sum(self.stats.values()) - self.stats['pages']
        print("\n" + "═" * 70)
        print("  SUMMARY")
        print("═" * 70)
        print(f"  Pages processed:       {self.stats['pages']}")
        print(f"  Annotations removed:   {self.stats['annotations']}")
        print(f"  Images removed:        {self.stats['images']}")
        print(f"  Text blocks removed:   {self.stats['text_blocks']}")
        print(f"  Metadata cleaned:      {self.stats['metadata']}")
        print(f"  ───────────────────────")
        print(f"  TOTAL REMOVED:         {total}")
        print(f"  Export format:         {self.export_format.upper()}")
        if self.export_format in ['png', 'tif']:
            print(f"  Resolution:            {self.dpi} DPI")
        print("═" * 70)
    
    def contains_watermark(self, text):
        if not text:
            return False
        text_str = str(text).lower()
        return any(kw.lower() in text_str for kw in self.config.WATERMARK_KEYWORDS)
    
    def is_watermark_url(self, url):
        if not url:
            return False
        url_str = str(url).lower()
        return any(p in url_str for p in self.config.WATERMARK_URLS)
    
    def remove_annotations(self, pdf):
        removed = 0
        for page in pdf.pages:
            if Name.Annots not in page:
                continue
            annots = page.Annots
            if not isinstance(annots, Array):
                continue
            
            to_remove = []
            for i, annot_ref in enumerate(annots):
                try:
                    annot = annot_ref
                    if not isinstance(annot, Dictionary):
                        continue
                    
                    if Name.A in annot:
                        action = annot.A
                        if isinstance(action, Dictionary) and Name.URI in action:
                            uri = str(action.URI)
                            if self.is_watermark_url(uri):
                                self.log(f"Removing annotation: {uri[:50]}", 'ACTION')
                                to_remove.append(i)
                                continue
                    
                    if Name.Contents in annot:
                        contents = str(annot.Contents)
                        if self.contains_watermark(contents):
                            self.log("Removing watermark annotation", 'ACTION')
                            to_remove.append(i)
                except:
                    pass
            
            for i in reversed(to_remove):
                del annots[i]
                removed += 1
        
        return removed
    
    def remove_watermark_images(self, pdf):
        removed = 0
        
        for page_num, page in enumerate(pdf.pages):
            if Name.Resources not in page:
                continue
            
            resources = page.Resources
            if Name.XObject not in resources:
                continue
            
            xobjects = resources.XObject
            all_keys = list(xobjects.keys())
            
            self.log(f"Page {page_num + 1}: Checking {len(all_keys)} XObject(s)", 'DEBUG')
            
            to_remove = []
            
            for key in all_keys:
                try:
                    xobj = xobjects[key]
                    
                    try:
                        subtype = xobj.get(Name.Subtype) if hasattr(xobj, 'get') else xobj.Subtype
                    except:
                        subtype = None
                    
                    if subtype != Name.Image:
                        try:
                            if xobj.Subtype != Name.Image:
                                continue
                        except:
                            continue
                    
                    try:
                        width = int(xobj.get(Name.Width) if hasattr(xobj, 'get') else xobj.Width)
                        height = int(xobj.get(Name.Height) if hasattr(xobj, 'get') else xobj.Height)
                    except:
                        continue
                    
                    self.log(f"  XObject {key}: {width}x{height}px", 'DEBUG')
                    
                    is_main = (width >= self.config.MAIN_CONTENT_THRESHOLD and 
                              height >= self.config.MAIN_CONTENT_THRESHOLD)
                    
                    if not is_main:
                        self.log(f"  Removing {key} ({width}x{height}px)", 'ACTION')
                        to_remove.append(key)
                
                except:
                    pass
            
            # Clean content streams BEFORE removing from resources
            if to_remove:
                self._clean_content_references(page, to_remove)
            
            # Now remove from resources
            for key in to_remove:
                try:
                    del xobjects[key]
                    removed += 1
                except:
                    pass
        
        return removed
    
    def _clean_content_references(self, page, removed_keys):
        """Enhanced content stream cleaning to remove all XObject references"""
        if Name.Contents not in page:
            return
        
        contents = page.Contents
        if not isinstance(contents, Array):
            contents = [contents]
        
        for stream_ref in contents:
            try:
                stream = stream_ref
                if not hasattr(stream, 'read_bytes'):
                    continue
                
                data = stream.read_bytes().decode('latin-1', errors='ignore')
                original_length = len(data)
                
                # Multiple passes to ensure all references are removed
                for key in removed_keys:
                    key_str = str(key)
                    
                    # Pattern 1: /KeyName Do (most common)
                    data = re.sub(rf'/{re.escape(key_str)}\s+Do\s*', '', data)
                    
                    # Pattern 2: q ... /KeyName Do ... Q (save/restore graphics state)
                    data = re.sub(rf'q\s+[^Q]*?/{re.escape(key_str)}\s+Do[^Q]*?Q', '', data)
                    
                    # Pattern 3: cm (transformation matrix) followed by /KeyName Do
                    data = re.sub(rf'[\d\.\-\s]+cm\s+/{re.escape(key_str)}\s+Do', '', data)
                    
                    # Pattern 4: Just the key reference
                    data = re.sub(rf'/{re.escape(key_str)}\b', '', data)
                    
                    # Pattern 5: Graphics state with transformation and Do
                    data = re.sub(rf'[\d\.\-\s]+[\d\.\-\s]+[\d\.\-\s]+[\d\.\-\s]+[\d\.\-\s]+[\d\.\-\s]+cm\s+/{re.escape(key_str)}\s+Do', '', data)
                
                # Clean up any resulting empty graphics state blocks
                data = re.sub(r'q\s+Q', '', data)
                
                # Clean up multiple consecutive whitespace/newlines
                data = re.sub(r'\n\s*\n\s*\n', '\n\n', data)
                
                # Only write if we actually changed something
                if len(data) != original_length:
                    stream.write(data.encode('latin-1'))
                    self.log(f"  Cleaned {original_length - len(data)} bytes from content stream", 'DEBUG')
            
            except Exception as e:
                self.log(f"  Warning: Could not clean content stream: {e}", 'WARNING')
                pass
    
    def remove_text_watermarks(self, pdf):
        removed = 0
        
        for page in pdf.pages:
            if Name.Contents not in page:
                continue
            
            contents = page.Contents
            if not isinstance(contents, Array):
                contents = [contents]
            
            for stream_ref in contents:
                try:
                    stream = stream_ref
                    if not hasattr(stream, 'read_bytes'):
                        continue
                    
                    data = stream.read_bytes().decode('latin-1', errors='ignore')
                    lines = data.split('\n')
                    cleaned = []
                    
                    i = 0
                    while i < len(lines):
                        line = lines[i]
                        
                        if line.strip() == 'BT':
                            block = [line]
                            i += 1
                            
                            while i < len(lines):
                                block.append(lines[i])
                                if lines[i].strip() == 'ET':
                                    i += 1
                                    break
                                i += 1
                            
                            block_text = '\n'.join(block)
                            if self.contains_watermark(block_text):
                                self.log("Removing watermark text block", 'ACTION')
                                removed += 1
                            else:
                                cleaned.extend(block)
                        else:
                            cleaned.append(line)
                            i += 1
                    
                    if removed > 0:
                        stream.write('\n'.join(cleaned).encode('latin-1'))
                except:
                    pass
        
        return removed
    
    def clean_metadata(self, pdf):
        removed = 0
        if not pdf.trailer.get(Name.Info):
            return 0
        
        info = pdf.trailer.Info
        keys = [Name.Title, Name.Subject, Name.Author, Name.Keywords, Name.Creator, Name.Producer]
        
        for key in keys:
            if key in info:
                val = str(info[key])
                if self.contains_watermark(val):
                    self.log(f"Cleaning metadata: {key}", 'ACTION')
                    del info[key]
                    removed += 1
        
        return removed
    
    def export_to_pdf(self, pdf, output):
        self.log(f"Saving PDF: {output}", 'ACTION')
        pdf.save(output)
        self.log("PDF saved", 'SUCCESS')
    
    def export_to_png(self, pdf_path, output_base):
        self.log(f"Exporting to PNG (DPI: {self.dpi})...", 'ACTION')
        
        try:
            doc = fitz.open(pdf_path)
        except Exception as e:
            self.log(f"Failed to open PDF for export: {e}", 'ERROR')
            return []
        
        files = []
        
        for i in range(len(doc)):
            try:
                page = doc[i]
                zoom = self.dpi / 72
                mat = fitz.Matrix(zoom, zoom)
                
                # Render with error messages suppressed
                with self.suppress_stderr():
                    try:
                        pix = page.get_pixmap(matrix=mat, alpha=False)
                    except Exception as e:
                        # Try again with default settings
                        try:
                            pix = page.get_pixmap(alpha=False)
                        except:
                            self.log(f"  Error: Could not render page {i + 1}, skipping", 'ERROR')
                            continue
                
                if len(doc) == 1:
                    out = f"{output_base}.png"
                else:
                    out = f"{output_base}_page_{i + 1}.png"
                
                pix.save(out)
                files.append(out)
                self.log(f"  Page {i + 1} → {out}", 'SUCCESS')
            
            except Exception as e:
                self.log(f"  Error on page {i + 1}: {e}", 'ERROR')
                continue
        
        doc.close()
        return files
    
    def export_to_tif(self, pdf_path, output):
        self.log(f"Exporting to multi-page TIF (DPI: {self.dpi})...", 'ACTION')
        
        try:
            doc = fitz.open(pdf_path)
        except Exception as e:
            self.log(f"Failed to open PDF for export: {e}", 'ERROR')
            return None
        
        images = []
        
        for i in range(len(doc)):
            try:
                page = doc[i]
                zoom = self.dpi / 72
                mat = fitz.Matrix(zoom, zoom)
                
                # Render with error messages suppressed
                with self.suppress_stderr():
                    try:
                        pix = page.get_pixmap(matrix=mat, alpha=False)
                    except Exception as e:
                        # Try again with default settings
                        try:
                            pix = page.get_pixmap(alpha=False)
                        except:
                            self.log(f"  Error: Could not render page {i + 1}, skipping", 'ERROR')
                            continue
                
                img_bytes = pix.tobytes("png")
                img = Image.open(BytesIO(img_bytes))
                images.append(img)
                
                self.log(f"  Converted page {i + 1}", 'DEBUG')
            
            except Exception as e:
                self.log(f"  Error on page {i + 1}: {e}", 'ERROR')
                continue
        
        doc.close()
        
        if images:
            try:
                images[0].save(
                    output,
                    save_all=True,
                    append_images=images[1:] if len(images) > 1 else [],
                    compression="tiff_deflate",
                    dpi=(self.dpi, self.dpi)
                )
                self.log(f"TIF saved: {output}", 'SUCCESS')
                return output
            except Exception as e:
                self.log(f"Failed to save TIF: {e}", 'ERROR')
                return None
        else:
            self.log("No images to save", 'ERROR')
            return None
    
    def process(self, input_path, output_path=None):
        self.print_header()
        
        if not os.path.exists(input_path):
            self.log(f"File not found: {input_path}", 'ERROR')
            return False
        
        input_file = Path(input_path)
        
        if output_path is None:
            if self.export_format == 'pdf':
                output_path = str(input_file.parent / f"{input_file.stem}_cleaned.pdf")
            elif self.export_format == 'png':
                output_path = str(input_file.parent / f"{input_file.stem}_cleaned")
            elif self.export_format == 'tif':
                output_path = str(input_file.parent / f"{input_file.stem}_cleaned.tif")
        
        self.log(f"Input:  {input_path}", 'INFO')
        self.log(f"Output: {output_path}", 'INFO')
        self.log(f"Format: {self.export_format.upper()}", 'INFO')
        if self.export_format in ['png', 'tif']:
            self.log(f"DPI:    {self.dpi}\n", 'INFO')
        
        self.log("Phase 1: Loading PDF", 'ACTION')
        try:
            pdf = Pdf.open(input_path, allow_overwriting_input=True)
        except Exception as e:
            self.log(f"Failed to open: {e}", 'ERROR')
            return False
        
        self.stats['pages'] = len(pdf.pages)
        self.log(f"Loaded {self.stats['pages']} page(s)", 'SUCCESS')
        
        self.log("\nPhase 2: Removing watermarks", 'ACTION')
        
        self.log("  Step 1: Annotations...", 'INFO')
        self.stats['annotations'] = self.remove_annotations(pdf)
        self.log(f"  Removed {self.stats['annotations']} annotation(s)", 'SUCCESS')
        
        self.log("  Step 2: Images...", 'INFO')
        self.stats['images'] = self.remove_watermark_images(pdf)
        self.log(f"  Removed {self.stats['images']} image(s)", 'SUCCESS')
        
        self.log("  Step 3: Text...", 'INFO')
        self.stats['text_blocks'] = self.remove_text_watermarks(pdf)
        self.log(f"  Removed {self.stats['text_blocks']} text block(s)", 'SUCCESS')
        
        self.log("  Step 4: Metadata...", 'INFO')
        self.stats['metadata'] = self.clean_metadata(pdf)
        self.log(f"  Cleaned {self.stats['metadata']} field(s)", 'SUCCESS')
        
        self.log("\nPhase 3: Exporting", 'ACTION')
        
        temp_pdf = str(input_file.parent / f"_temp_{os.getpid()}.pdf")
        
        try:
            # Save with linearization for better compatibility
            pdf.save(temp_pdf, linearize=True)
            pdf.close()
            time.sleep(0.3)
            
            result = None
            
            if self.export_format == 'pdf':
                try:
                    os.replace(temp_pdf, output_path)
                except:
                    import shutil
                    shutil.copy2(temp_pdf, output_path)
                    os.remove(temp_pdf)
                self.log(f"Saved: {output_path}", 'SUCCESS')
                result = [output_path]
            
            elif self.export_format == 'png':
                result = self.export_to_png(temp_pdf, output_path)
                time.sleep(0.3)
                try:
                    os.remove(temp_pdf)
                except:
                    pass
                if not result:
                    return False
            
            elif self.export_format == 'tif':
                out = self.export_to_tif(temp_pdf, output_path)
                time.sleep(0.3)
                try:
                    os.remove(temp_pdf)
                except:
                    pass
                if out:
                    result = [out]
                else:
                    return False
            
            self.print_summary()
            return result
        
        except Exception as e:
            self.log(f"Export failed: {e}", 'ERROR')
            try:
                if os.path.exists(temp_pdf):
                    time.sleep(0.3)
                    os.remove(temp_pdf)
            except:
                pass
            return False


def print_usage():
    print(f"\n{Config.BRAND}")
    print("=" * 70)
    print("\nUsage:")
    print("  python watermark_remover.py input.pdf")
    print("  python watermark_remover.py input.pdf --format pdf")
    print("  python watermark_remover.py input.pdf --format png")
    print("  python watermark_remover.py input.pdf --format tif")
    print("  python watermark_remover.py input.pdf --format png --dpi 600")
    print("  python watermark_remover.py input.pdf --output custom.pdf")
    print("  python watermark_remover.py input.pdf --debug")
    print("\nExport Formats:")
    print("  pdf  - Clean PDF (default)")
    print("  png  - PNG images (one per page)")
    print("  tif  - Multi-page TIFF")
    print("\nOptions:")
    print("  --format FORMAT   Output format (pdf/png/tif)")
    print("  --dpi DPI        Resolution for PNG/TIF (default: 300)")
    print("  --output PATH    Custom output path")
    print("  --debug          Show debug info")
    print("\nCreated by: xsukax")
    print("=" * 70 + "\n")


def parse_args():
    args = {'input': None, 'output': None, 'format': 'pdf', 'dpi': 300, 'debug': False}
    
    i = 1
    while i < len(sys.argv):
        arg = sys.argv[i]
        
        if arg in ['--help', '-h']:
            print_usage()
            sys.exit(0)
        elif arg == '--format' and i + 1 < len(sys.argv):
            fmt = sys.argv[i + 1].lower()
            if fmt not in ['pdf', 'png', 'tif', 'tiff']:
                print(f"❌ Invalid format. Use: pdf, png, or tif")
                sys.exit(1)
            args['format'] = 'tif' if fmt == 'tiff' else fmt
            i += 2
        elif arg == '--dpi' and i + 1 < len(sys.argv):
            try:
                dpi = int(sys.argv[i + 1])
                if dpi < 72 or dpi > 1200:
                    print(f"❌ DPI must be 72-1200")
                    sys.exit(1)
                args['dpi'] = dpi
            except:
                print(f"❌ Invalid DPI")
                sys.exit(1)
            i += 2
        elif arg == '--output' and i + 1 < len(sys.argv):
            args['output'] = sys.argv[i + 1]
            i += 2
        elif arg in ['--debug', '-d']:
            args['debug'] = True
            i += 1
        elif not arg.startswith('-'):
            if args['input'] is None:
                args['input'] = arg
            i += 1
        else:
            print(f"❌ Unknown option: {arg}")
            print_usage()
            sys.exit(1)
    
    return args


def main():
    args = parse_args()
    
    if args['input'] is None:
        print_usage()
        sys.exit(0)
    
    remover = XsukaxRemover(
        debug=args['debug'],
        export_format=args['format'],
        dpi=args['dpi']
    )
    
    result = remover.process(args['input'], args['output'])
    
    if result:
        if len(result) == 1:
            print(f"\n✓ Success! Saved: {result[0]}\n")
        else:
            print(f"\n✓ Success! Created {len(result)} file(s):")
            for f in result:
                print(f"  → {f}")
            print()
        sys.exit(0)
    else:
        print(f"\n✗ Failed\n")
        sys.exit(1)


if __name__ == '__main__':
    main()