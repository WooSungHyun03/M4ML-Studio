export function screenToImage(
  clientX: number,
  clientY: number,
  rect: { left: number; top: number; width: number; height: number },
  width: number,
  height: number,
) {
  if (rect.width <= 0 || rect.height <= 0 || width <= 0 || height <= 0)
    throw new Error("사진 크기가 유효하지 않습니다.");
  return {
    x: Math.max(
      0,
      Math.min(width - 1, ((clientX - rect.left) * width) / rect.width),
    ),
    y: Math.max(
      0,
      Math.min(height - 1, ((clientY - rect.top) * height) / rect.height),
    ),
  };
}
