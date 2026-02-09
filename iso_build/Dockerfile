FROM alpine:latest

# Install tools required for building the ISO
RUN apk add --no-cache \
    syslinux \
    xorriso \
    squashfs-tools \
    mtools \
    dosfstools \
    findutils \
    bash \
    sed \
    docker-cli \
    cpio \
    gzip

# Copy the build script
COPY gen_iso.sh /gen_iso.sh
# Fix potential CRLF issues from Windows and make executable
RUN sed -i 's/\r$//' /gen_iso.sh && chmod +x /gen_iso.sh

WORKDIR /
ENTRYPOINT ["/bin/bash", "/gen_iso.sh"]
