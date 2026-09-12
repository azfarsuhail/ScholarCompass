from app.routers.documents import _resolved_content_type


def test_octet_stream_pdf_by_magic_header_is_accepted():
    got = _resolved_content_type("application/octet-stream", b"%PDF-1.7\n...", "upload.bin")
    assert got == "application/pdf"


def test_octet_stream_pdf_by_filename_is_accepted():
    got = _resolved_content_type("application/octet-stream", b"not-a-real-pdf", "resume.PDF")
    assert got == "application/pdf"


def test_octet_stream_non_pdf_stays_rejected():
    got = _resolved_content_type("application/octet-stream", b"\x89PNG\r\n", "photo.png")
    assert got == "application/octet-stream"


def test_known_type_is_unchanged():
    got = _resolved_content_type("image/jpeg", b"jpeg-bytes", "scan.jpg")
    assert got == "image/jpeg"
