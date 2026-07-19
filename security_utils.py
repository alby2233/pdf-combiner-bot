import fitz

def encrypt_pdf(input_path, output_path, password):
    doc = fitz.open(input_path)
    # Encrypt PDF using strong AES-256 encryption
    doc.save(
        output_path, 
        encryption=fitz.PDF_ENCRYPT_AES_256, 
        user_pw=password, 
        owner_pw=password
    )
    doc.close()

def decrypt_pdf(input_path, output_path, password):
    doc = fitz.open(input_path)
    if doc.is_encrypted:
        success = doc.authenticate(password)
        if not success:
            doc.close()
            raise ValueError("Incorrect password! Please try again.")
    # Save decrypted copy
    doc.save(output_path)
    doc.close()
