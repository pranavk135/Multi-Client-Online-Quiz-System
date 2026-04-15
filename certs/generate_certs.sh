#!/bin/bash
# ── QuizNet Certificate Generator (Linux/macOS) ──────────────────────────
# Generates a self-signed TLS certificate for the quiz server.
# Requires: openssl (usually pre-installed on Linux/macOS)
# ─────────────────────────────────────────────────────────────────────────

echo "============================================"
echo "  QuizNet - TLS Certificate Generator"
echo "============================================"
echo

# Check if OpenSSL is available
if ! command -v openssl &> /dev/null; then
    echo "ERROR: OpenSSL is not installed."
    echo "Install via:"
    echo "  Ubuntu/Debian: sudo apt install openssl"
    echo "  macOS:         brew install openssl"
    exit 1
fi

# Show network interfaces
echo "Your network interfaces:"
echo
if command -v ip &> /dev/null; then
    ip -4 addr show | grep inet
elif command -v ifconfig &> /dev/null; then
    ifconfig | grep "inet "
fi
echo

# Get server IP from user
read -p "Enter your server's LAN IP address (e.g. 192.168.1.42): " SERVER_IP

if [ -z "$SERVER_IP" ]; then
    echo "ERROR: IP address cannot be empty."
    exit 1
fi

echo
echo "Updating openssl.cnf with IP: $SERVER_IP"
echo

# Create the openssl.cnf with the provided IP
cat > openssl.cnf << EOF
[req]
default_bits       = 2048
prompt             = no
default_md         = sha256
distinguished_name = dn
x509_extensions    = v3_req

[dn]
C  = IN
ST = Karnataka
L  = Bangalore
O  = QuizNet
CN = QuizNet

[v3_req]
subjectAltName = @alt_names
basicConstraints = CA:FALSE
keyUsage = digitalSignature, keyEncipherment

[alt_names]
IP.1  = 127.0.0.1
DNS.1 = localhost
IP.2  = $SERVER_IP
EOF

# Generate the certificate and key
echo "Generating certificate and key..."
openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
    -keyout key.pem \
    -out cert.pem \
    -config openssl.cnf

if [ $? -eq 0 ]; then
    echo
    echo "============================================"
    echo "  Certificate generated successfully!"
    echo "============================================"
    echo "  cert.pem  : TLS certificate"
    echo "  key.pem   : Private key"
    echo "  Valid for : 365 days"
    echo "  Server IP : $SERVER_IP"
    echo "============================================"
    echo
    echo "You can now start the server:"
    echo "  python server.py"
    echo "  python web_server.py"
else
    echo
    echo "ERROR: Certificate generation failed."
    echo "Check that OpenSSL is properly installed."
fi
