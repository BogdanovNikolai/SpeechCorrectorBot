# merge_project.py

import os

def read_file(filename):
    with open(filename, 'r', encoding='utf-8') as f:
        return f.read()

def write_file(filename, content):
    with open(filename, 'w', encoding='utf-8') as f:
        f.write(content)

def merge_files(file_list, output_file):
    merged = ""
    for file in file_list:
        if not os.path.exists(file):
            print(f"[!] Файл не найден: {file}")
            continue
        content = read_file(file)
        merged += f"\n\n# === {file} ===\n\n"
        merged += content
    write_file(output_file, merged)
    print(f"[+] Все файлы объединены в {output_file}")

if __name__ == "__main__":
    files = [
        "ai.py",
        "telegram_bot.py",
        "main.py"
    ]
    output = "speech_corrector_single_file.py"

    merge_files(files, output)