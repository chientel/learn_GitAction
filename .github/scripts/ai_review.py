import os
import sys
import requests
from google import genai
from google.genai import types

def get_changed_files(repo, pr_number, token):
    """Lấy danh sách các file và nội dung thay đổi trong PR"""
    url = f"https://api.github.com/repos/{repo}/pulls/{pr_number}/files"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github.v3+json"
    }
    response = requests.get(url, headers=headers)
    if response.status_code != 200:
        print(f"Không thể lấy danh sách file: {response.text}")
        sys.exit(1)
    return response.json()

def post_comment(repo, pr_number, token, body):
    """Gửi comment kết quả lên Pull Request"""
    url = f"https://api.github.com/repos/{repo}/issues/{pr_number}/comments"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github.v3+json"
    }
    response = requests.post(url, headers=headers, json={"body": body})
    return response.status_code == 201

def main():
    # Đọc các biến môi trường từ GitHub Action
    api_key = os.getenv("GEMINI_API_KEY")
    github_token = os.getenv("GITHUB_TOKEN")
    repo = os.getenv("REPOSITORY")
    pr_number = os.getenv("PR_NUMBER")

    if not api_key:
        print("Thiếu GEMINI_API_KEY")
        sys.exit(1)

    # Khởi tạo Gemini Client (Sử dụng SDK mới nhất `google-genai`)
    client = genai.Client(api_key=api_key)
    
    # Lấy các file thay đổi
    files = get_changed_files(repo, pr_number, github_token)
    
    review_results = "### 🤖 AI Code Review - Coding Convention\n\n"
    has_suggestions = False

    for file in files:
        filename = file['filename']
        # Bỏ qua các file cấu hình, lock file nếu cần thiết
        if filename.endswith(('json', 'md', 'lock', 'yml', 'yaml')):
            continue
            
        patch = file.get('patch') # Đoạn code thay đổi (diff)
        if not patch:
            continue

        # Định nghĩa Prompt cho Gemini
        prompt = f"""
        Bạn là một Tech Lead nghiêm túc và giàu kinh nghiệm. Hãy kiểm tra đoạn code thay đổi (diff) dưới đây của file `{filename}` xem có vi phạm coding convention tiêu chuẩn của ngôn ngữ đó không (ví dụ: PEP8 cho Python, Clean Code, đặt tên biến, cấu trúc hàm, comment...).

        Nếu có lỗi hoặc điểm cần cải tiến, hãy chỉ rõ:
        1. Vị trí/Dòng code (nếu có).
        2. Lý do vi phạm.
        3. Cách sửa lại cho đúng.

        Nếu đoạn code đã chuẩn convention, chỉ cần trả về đúng từ: "OK".
        
        Đoạn code thay đổi:
        ```
        {patch}
        
    """

        try:
            # Sử dụng model gemini-2.5-flash để tối ưu tốc độ và chi phí
            response = client.models.generate_content(
                model='gemini-2.5-flash',
                contents=prompt,
            )
            
            result = response.text.strip()
            if result != "OK":
                has_suggestions = True
                review_results += f"#### 📁 File: `{filename}`\n{result}\n\n---\n"
        except Exception as e:
            print(f"Lỗi khi gọi Gemini API cho file {filename}: {e}")

    if has_suggestions:
        post_comment(repo, pr_number, github_token, review_results)
        print("Đã gửi nhận xét lên PR.")
    else:
        post_comment(repo, pr_number, github_token, "### 🤖 AI Code Review\n\n✅ Tất cả các file thay đổi đều đạt chuẩn coding convention!")
        print("Code sạch! Không có vi phạm.")

if __name__ == "__main__":
    main()