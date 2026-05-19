import os
import sys
import time
import requests
from google import genai
from google.genai import types
from google.genai.errors import APIError

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

def call_gemini_with_retry(client, prompt, retries=3, delay=2):
    """Gói gọi Gemini API với cơ chế nhận diện lỗi 503/429 chính xác để retry"""
    for attempt in range(retries):
        try:
            response = client.models.generate_content(
                model='gemini-2.5-flash',
                contents=prompt,
            )
            return response.text.strip(), True
            
        except APIError as e:
            # Lấy thông tin lỗi dưới dạng chuỗi để check cho chắc chắn
            err_code = str(getattr(e, 'code', '') or '')
            err_status = str(getattr(e, 'status', '') or '').upper()
            err_message = str(e.message or '').upper()
            
            # Kiểm tra xem có phải lỗi quá tải/bận không (503, 429, UNAVAILABLE, RESOURCE_EXHAUSTED)
            is_overloaded = (
                "503" in err_code or 
                "429" in err_code or 
                "UNAVAILABLE" in err_status or 
                "RESOURCE_EXHAUSTED" in err_status or
                "TEMPORARY" in err_message
            )
            
            if is_overloaded and attempt < retries - 1:
                print(f"Gemini API đang bận (Status: {err_status or err_code}). Thử lại sau {delay} giây... (Lần {attempt + 1}/{retries})")
                time.sleep(delay)
                delay *= 2
                continue  # Tiếp tục vòng lặp để thử lại
                
            # Nếu là lỗi khác (như 400, 403) hoặc đã hết lượt thử lại
            return f"Lỗi API ({err_status or err_code}): {e.message}", False
            
        except Exception as e:
            return f"Lỗi hệ thống: {str(e)}", False
            
    return "Hết lượt thử lại do API quá tải.", False

def main():
    api_key = os.getenv("GEMINI_API_KEY")
    github_token = os.getenv("GITHUB_TOKEN")
    repo = os.getenv("REPOSITORY")
    pr_number = os.getenv("PR_NUMBER")

    if not api_key:
        print("Thiếu GEMINI_API_KEY")
        sys.exit(1)

    client = genai.Client(api_key=api_key)
    files = get_changed_files(repo, pr_number, github_token)
    
    review_results = "### 🤖 AI Code Review - Coding Convention\n\n"
    has_suggestions = False
    has_errors = False
    error_details = ""

    for file in files:
        filename = file['filename']
        if filename.endswith(('json', 'md', 'lock', 'yml', 'yaml')):
            continue
            
        patch = file.get('patch')
        if not patch:
            continue

        prompt = f"""
        Bạn là một Tech Lead nghiêm túc và giàu kinh nghiệm. Hãy kiểm tra đoạn code thay đổi (diff) dưới đây của file `{filename}` xem có vi phạm coding convention tiêu chuẩn của ngôn ngữ đó không (ví dụ: Clean Code, đặt tên biến, cấu trúc hàm, comment...).

        Nếu có lỗi hoặc điểm cần cải tiến, hãy chỉ rõ:
        1. Vị trí/Dòng code (nếu có).
        2. Lý do vi phạm.
        3. Cách sửa lại cho đúng.

        Nếu đoạn code đã chuẩn convention, chỉ cần trả về đúng từ: "OK".
        chu y code review chi can tap trung vao coding convention, khong can review ve logic.
        Đoạn code thay đổi:
        ```
        {patch}
        
    """

        result, success = call_gemini_with_retry(client, prompt)
        
        if success:
            if result != "OK":
                has_suggestions = True
                review_results += f"#### 📁 File: `{filename}`\n{result}\n\n---\n"
        else:
            has_errors = True
            error_details += f"❌ Không thể review file `{filename}`: {result}\n"
            print(f"Thất bại khi review {filename}: {result}")

    # Xử lý kết quả cuối cùng để post lên PR
    if has_errors:
        final_comment = review_results if has_suggestions else "### 🤖 AI Code Review\n\n"
        final_comment += f"⚠️ **Lưu ý:** Quá trình review gặp một số sự cố gián đoạn:\n{error_details}"
        post_comment(repo, pr_number, github_token, final_comment)
    elif has_suggestions:
        post_comment(repo, pr_number, github_token, review_results)
    else:
        post_comment(repo, pr_number, github_token, "### 🤖 AI Code Review\n\n✅ Tất cả các file thay đổi đều đạt chuẩn coding convention!")

if __name__ == "__main__":
    main()