from flask import Flask, render_template, request, jsonify
from crawler import fetch_characters, save_characters, init_db

app = Flask(__name__)

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/search", methods=["POST"])
def search():
    adven_name = request.json.get("adven_name", "").strip()
    if not adven_name:
        return jsonify({"error": "모험단명을 입력해주세요."}), 400

    characters = fetch_characters(adven_name)
    if not characters:
        return jsonify({"error": "캐릭터를 찾지 못했습니다."}), 404

    save_characters(characters)
    return jsonify({"characters": characters})

if __name__ == "__main__":
    init_db()
    app.run(debug=True)
