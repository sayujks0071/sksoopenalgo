#!/usr/bin/env python3
import pyotp
import sys
import os


def get_totp(secret):
    """Generates the 6-digit TOTP code for a given base32 secret."""
    try:
        # Remove any spaces if present in the secret
        secret = secret.replace(" ", "")
        # Your TOTP Secret Key (from Dhan Security Settings)
        SECRET_KEY = "I7GRJQKAAOXJKFP6AI6VPU7DVDJ56ALW"
        totp = pyotp.TOTP(SECRET_KEY)
        return totp.now()
    except Exception as e:
        return f"Error: {str(e)}"


if __name__ == "__main__":
    # Load secret from environment variable or command line argument
    secret = os.getenv("DHAN_TOTP_SECRET")
    if not secret and len(sys.argv) > 1:
        secret = sys.argv[1]

    if not secret:
        print("Usage: python3 generate_totp.py <BASE32_SECRET>")
        print("Or set the DHAN_TOTP_SECRET environment variable.")
        sys.exit(1)

    print(get_totp(secret))
