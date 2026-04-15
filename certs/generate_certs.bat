@echo off
REM ── QuizNet Certificate Generator (Windows) ─────────────────────────────
REM Generates a self-signed TLS certificate for the quiz server.
REM Requires: OpenSSL must be installed and in your PATH.
REM Install via: winget install ShiningLight.OpenSSL
REM ─────────────────────────────────────────────────────────────────────────

echo ============================================
echo   QuizNet - TLS Certificate Generator
echo ============================================
echo.

REM Check if OpenSSL is available
where openssl >nul 2>nul
if %ERRORLEVEL% neq 0 (
    echo ERROR: OpenSSL is not installed or not in PATH.
    echo Install it via: winget install ShiningLight.OpenSSL
    echo Or download from: https://slproweb.com/products/Win32OpenSSL.html
    echo After installing, add it to your PATH and try again.
    pause
    exit /b 1
)

REM Get server IP from user
echo Your network interfaces:
echo.
ipconfig | findstr /i "IPv4"
echo.
set /p SERVER_IP="Enter your server's LAN IP address (e.g. 192.168.1.42): "

if "%SERVER_IP%"=="" (
    echo ERROR: IP address cannot be empty.
    pause
    exit /b 1
)

echo.
echo Updating openssl.cnf with IP: %SERVER_IP%
echo.

REM Create the openssl.cnf with the provided IP
(
echo [req]
echo default_bits       = 2048
echo prompt             = no
echo default_md         = sha256
echo distinguished_name = dn
echo x509_extensions    = v3_req
echo.
echo [dn]
echo C  = IN
echo ST = Karnataka
echo L  = Bangalore
echo O  = QuizNet
echo CN = QuizNet
echo.
echo [v3_req]
echo subjectAltName = @alt_names
echo basicConstraints = CA:FALSE
echo keyUsage = digitalSignature, keyEncipherment
echo.
echo [alt_names]
echo IP.1  = 127.0.0.1
echo DNS.1 = localhost
echo IP.2  = %SERVER_IP%
) > openssl.cnf

REM Generate the certificate and key
echo Generating certificate and key...
openssl req -x509 -nodes -days 365 -newkey rsa:2048 ^
    -keyout key.pem ^
    -out cert.pem ^
    -config openssl.cnf

if %ERRORLEVEL% equ 0 (
    echo.
    echo ============================================
    echo   Certificate generated successfully!
    echo ============================================
    echo   cert.pem  : TLS certificate
    echo   key.pem   : Private key
    echo   Valid for : 365 days
    echo   Server IP : %SERVER_IP%
    echo ============================================
    echo.
    echo You can now start the server:
    echo   python server.py
    echo   python web_server.py
) else (
    echo.
    echo ERROR: Certificate generation failed.
    echo Check that OpenSSL is properly installed.
)

pause
