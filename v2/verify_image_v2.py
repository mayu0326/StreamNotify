import sys
import os
from PIL import Image
import io

# v2をパスに追加
sys.path.append(os.getcwd())
import image_processor


def test_resize():
    print("--- Image Processor Verification Start ---")
    # 4000x3000の大きなダミー画像を作成
    img = Image.new("RGB", (4000, 3000), color=(73, 109, 137))
    img_byte_arr = io.BytesIO()
    img.save(img_byte_arr, format="JPEG")
    img_data = img_byte_arr.getvalue()

    print(f"Original size: {len(img_data) / 1024:.2f} KB")

    # リサイズ実行
    processed_data = image_processor.resize_image_v2(img_data)

    if processed_data:
        processed_size_kb = len(processed_data) / 1024
        print(f"Processed size: {processed_size_kb:.2f} KB")
        # 1MB (1000KB) 以下であることを確認
        if len(processed_data) <= 1000000:
            print("Verification SUCCESS: Image is under 1MB")
        else:
            print(
                f"Verification FAILED: Image is over 1MB ({processed_size_kb:.2f} KB)"
            )

        # アスペクト比の確認
        processed_img = Image.open(io.BytesIO(processed_data))
        print(f"Processed dimensions: {processed_img.size}")
    else:
        print("Verification FAILED: No data returned")
    print("--- Image Processor Verification End ---")


if __name__ == "__main__":
    try:
        test_resize()
    except Exception as e:
        print(f"Error during verification: {e}")
