# Included by nginx.conf in the server block and in every location that sets a header of its own.
add_header X-Frame-Options "DENY" always;
add_header X-Content-Type-Options "nosniff" always;
add_header Referrer-Policy "same-origin" always;
add_header Permissions-Policy "camera=(), microphone=(), geolocation=(), payment=(), usb=()" always;
add_header Strict-Transport-Security $hsts_header always;
# Written at container start by docker/env-config-entrypoint.sh (a default with frame-ancestors only ships in the image).
include /var/cache/nginx/content-security-policy.inc;
