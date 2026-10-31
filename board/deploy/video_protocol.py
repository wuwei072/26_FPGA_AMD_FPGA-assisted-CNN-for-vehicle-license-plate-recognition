"""视频帧：24字节小端包头，随后是JPEG和PNG两端共用"""
import struct

HEADER = struct.Struct("<I4hfII")
VIDEO_PORT = 8080
CONTROL_PORT = 8081


def pack_frame(frame_id, roi, dma_ms, color_data, edge_data):
    header = HEADER.pack(frame_id & 0xFFFFFFFF, *map(int, roi), float(dma_ms),
                         len(color_data), len(edge_data))
    return header + color_data + edge_data


def recv_exact(sock, length):
    data = bytearray()
    while len(data) < length:
        block = sock.recv(min(length - len(data), 65536))
        if not block:
            raise ConnectionError("连接已断开")
        data.extend(block)
    return bytes(data)


def recv_frame(sock):
    frame_id, x, y, w, h, dma_ms, color_len, edge_len = HEADER.unpack(
        recv_exact(sock, HEADER.size))
    if color_len == 0 or edge_len == 0:
        raise ValueError("收到空图像")
    return dict(frame_id=frame_id, roi=(x, y, w, h), dma_ms=dma_ms,
                color_data=recv_exact(sock, color_len),
                edge_data=recv_exact(sock, edge_len))
