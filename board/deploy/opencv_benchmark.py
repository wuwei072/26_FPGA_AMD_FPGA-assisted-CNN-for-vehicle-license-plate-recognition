"""板端按需调用的OpenCV参考算法：输入灰度帧，返回ROI与边缘统计"""

import cv2
import numpy as np

FRAME_WIDTH = 640
FRAME_HEIGHT = 480
GRID_COLUMNS = 8
GRID_ROWS = 6
GRID_COUNT = GRID_COLUMNS * GRID_ROWS
CELL_WIDTH = 80
CELL_HEIGHT = 80
BINARY_THRESHOLD = 80
ACTIVE_THRESHOLD = 768


def opencv_roi_pipeline(image):
    if image.shape != (FRAME_HEIGHT, FRAME_WIDTH):
        raise ValueError("需要640x480的灰度图")

    gx = cv2.Sobel(image, cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(image, cv2.CV_32F, 0, 1, ksize=3)
    magnitude = np.clip(np.abs(gx) + np.abs(gy), 0, 255).astype(np.uint8)

    # 四周清零，和FPGA的边界处理一致
    magnitude[0, :] = 0
    magnitude[-1, :] = 0
    magnitude[:, 0] = 0
    magnitude[:, -1] = 0
    binary_edge = np.where(magnitude >= BINARY_THRESHOLD, 255, 0).astype(np.uint8) #二值化

    # 统计白色格子
    grid_view = binary_edge.reshape(GRID_ROWS, CELL_HEIGHT, GRID_COLUMNS, CELL_WIDTH)
    grid_counts = np.count_nonzero(grid_view, axis=(1, 3)).astype(np.uint16)
    active_map = (grid_counts > ACTIVE_THRESHOLD).astype(np.uint8)
    _, labels, stats, _ = cv2.connectedComponentsWithStats(
        active_map, connectivity=4, ltype=cv2.CV_32S
    )

    best_label = 0
    best_size = 0
    for label in labels.flat:
        size = stats[label, cv2.CC_STAT_AREA]
        if label != 0 and size > best_size:
            best_label = int(label)
            best_size = int(size)

    roi_x = roi_y = roi_w = roi_h = 0
    reduction_x100 = 10000
    if best_label:
        x = int(stats[best_label, cv2.CC_STAT_LEFT])
        y = int(stats[best_label, cv2.CC_STAT_TOP])
        w = int(stats[best_label, cv2.CC_STAT_WIDTH])
        h = int(stats[best_label, cv2.CC_STAT_HEIGHT])
        roi_x, roi_y = x * CELL_WIDTH, y * CELL_HEIGHT
        roi_w, roi_h = w * CELL_WIDTH, h * CELL_HEIGHT
        reduction_x100 = ((GRID_COUNT - w * h) * 10000 + GRID_COUNT // 2) // GRID_COUNT

    return {
        "roi_x": roi_x, "roi_y": roi_y,
        "roi_w": roi_w, "roi_h": roi_h,
        "best_grids": best_size, "reduction_x100": reduction_x100,
        "edge": binary_edge, "grid_counts": grid_counts,
        "active_map": active_map, "labels": labels,
    }


def result_fields(result):
    return [
        int(result["roi_x"]), int(result["roi_y"]),
        int(result["roi_w"]), int(result["roi_h"]),
        int(result["best_grids"]), int(result["reduction_x100"]),
    ]
