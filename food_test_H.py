import os
import cv2
import pandas as pd
import json
from datetime import datetime, timedelta
from flask import Flask, render_template, request, Response, jsonify, session, url_for, redirect, flash
from ultralytics import YOLO
from PIL import Image, ImageDraw, ImageFont
import uuid
import collections
import shutil

# --- 설정 ---
# 파일 경로 설정
UPLOAD_FOLDER = "uploads"
RESULT_FOLDER = "results"
JOURNAL_FOLDER = "journal_images"
CSV_PATH = "food_info.csv"
USER_DATA_PATH = "users.json" # 사용자 정보 저장 파일

# Flask 앱과 Secret Key 설정
app = Flask(__name__)
app.secret_key = "a_very_complex_and_secure_secret_key_should_be_used"

# --- 초기화 ---
os.makedirs(os.path.join('static', UPLOAD_FOLDER), exist_ok=True)
os.makedirs(os.path.join('static', RESULT_FOLDER), exist_ok=True)
os.makedirs(os.path.join('static', JOURNAL_FOLDER), exist_ok=True)

model = YOLO("best_1003.pt")
names = model.names

try:
    camera = cv2.VideoCapture(0)
    if not camera.isOpened():
        raise ValueError("웹캠을 열 수 없습니다.")
except Exception as e:
    print(f"웹캠 초기화 오류: {e}")
    camera = None


def calculate_bmr(gender, age, height_cm, weight_kg):
    """
    미프린-세인트 공식(Mifflin-St Jeor)을 이용해 기초대사량(BMR)을 계산합니다.
    """
    
    # 성별 상수 설정
    # male = +5, female = -161
    if gender.lower() == 'male':
        gender_constant = 5
    elif gender.lower() == 'female':
        gender_constant = -161
    else:
        return None # 유효하지 않은 성별

    # BMR 계산: (10 * W) + (6.25 * H) - (5 * A) + S
    bmr = (10 * weight_kg) + (6.25 * height_cm) - (5 * age) + gender_constant
    
    return round(bmr, 0)

# --- 유틸리티 함수 (이전과 동일) ---
def load_user_data():
    if not os.path.exists(USER_DATA_PATH):
        return {}
    with open(USER_DATA_PATH, 'r') as f:
        return json.load(f)

def save_user_data(data):
    with open(USER_DATA_PATH, 'w') as f:
        json.dump(data, f, indent=4)

def load_journal_data():
    username = session.get('username')
    if not username: return {}
    user_journal_path = f"journal_{username}.json"
    if os.path.exists(user_journal_path):
        with open(user_journal_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {}

def save_journal_data(data):
    username = session.get('username')
    if not username: return
    user_journal_path = f"journal_{username}.json"
    with open(user_journal_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=4)

def generate_frames():
    global camera
    if camera is None or not camera.isOpened():
        img = cv2.imread(os.path.join('static', 'no_camera.png'))
        _, buffer = cv2.imencode('.jpg', img)
        frame = buffer.tobytes()
        while True:
            yield (b'--frame\r\n'
                   b'Content-Type: image/jpeg\r\n\r\n' + frame + b'\r\n')
    
    while True:
        success, frame = camera.read()
        if not success: break
        ret, buffer = cv2.imencode('.jpg', frame)
        frame = buffer.tobytes()
        yield (b'--frame\r\n'
               b'Content-Type: image/jpeg\r\n\r\n' + frame + b'\r\n')

def get_color_by_calorie(calorie: float):
    if calorie >= 500: return (255, 0, 0)
    elif calorie >= 200: return (255, 165, 0)
    else: return (0, 255, 0)

# ★★★ 신규 추가 함수: 일일 잔여 칼로리 계산 로직 ★★★
def calculate_daily_remaining_calories(username, selected_date):
    """
    유저의 BMR을 users.json에서 불러와, 특정 날짜의 총 섭취 칼로리를 뺀 잔여 칼로리를 계산합니다.
    """
    users = load_user_data() # users.json에서 BMR 로드
    
    # 1. 유저의 BMR 가져오기
    user_data = users.get(username)
    if not user_data or 'bmr' not in user_data:
        return None # BMR 정보가 없으면 계산 불가
    
    bmr = user_data.get('bmr', 0) # BMR 값
    
    # 2. 해당 날짜의 총 섭취 칼로리 계산
    # load_journal_data()는 현재 session['username']을 사용합니다.
    user_food_records = load_journal_data() 
    
    # 선택된 날짜의 기록 가져오기 (사용자가 제공한 JSON 구조)
    date_record = user_food_records.get(selected_date, {})
    daily_entries = date_record.get('entries', []) 
    
    total_consumed_calories = 0
    
    # entries 리스트를 순회하며 칼로리 합산
    for entry in daily_entries:
        results = entry.get('results', []) 
        for result in results:
            info = result.get('info', {})
            # 'kcal' 값을 가져와 합산합니다.
            kcal_value = info.get('kcal', 0.0)
            total_consumed_calories += kcal_value
            
    # 3. 잔여 칼로리 계산
    remaining_calories = bmr - total_consumed_calories
    
    return round(remaining_calories, 0)
# ★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★
    
# --- 라우팅 (Routing) ---

# 1. 인증 라우트 (이전과 동일)
@app.route('/')
def main_redirect():
    return redirect(url_for('login')) if 'username' not in session else redirect(url_for('index'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        users = load_user_data()
        
        # --- 수정된 부분 ---
        if username in users and users[username].get('password') == password:
        # -------------------
            session['username'] = username
            session['recent_foods'] = []
            return redirect(url_for('index'))
        else:
            flash('사용자 ID 또는 비밀번호가 올바르지 않습니다.')
            return redirect(url_for('login'))
    return render_template('login.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        
        # BMR 계산에 필요한 데이터
        try:
            age = int(request.form['age'])
            gender = request.form['gender']
            height = float(request.form['height'])
            weight = float(request.form['weight'])
        except ValueError:
            flash('나이, 키, 체중은 올바른 숫자 형식으로 입력해야 합니다.')
            return redirect(url_for('register'))
        except KeyError:
             # HTML 폼에 새 필드가 누락된 경우를 대비 (필요 없는 경우 이 부분을 제거해도 됨)
            flash('모든 필수 정보를 입력해야 합니다.')
            return redirect(url_for('register'))


        users = load_user_data()
        if username in users:
            flash('이미 존재하는 사용자 ID입니다.')
            return redirect(url_for('register'))
            
        # 기초대사량 (BMR) 계산
        bmr_value = calculate_bmr(gender, age, height, weight)
        
        if bmr_value is None:
            flash('성별 정보가 유효하지 않습니다.')
            return redirect(url_for('register'))

        # 사용자 정보에 비밀번호와 함께 건강 정보 및 BMR 추가 저장
        # 새로운 구조로 변경:
        users[username] = {
            'password': password,
            'age': age,
            'gender': gender,
            'height': height,
            'weight': weight,
            'bmr': bmr_value
        }
        
        save_user_data(users)
        flash(f'회원가입이 완료되었고, 기초대사량 ({bmr_value} kcal)이 저장되었습니다. 로그인해주세요.')
        return redirect(url_for('login'))
        
    # GET 요청: 회원가입 페이지 렌더링
    return render_template('register.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

# 2. 메인 애플리케이션 라우트
@app.route('/main')
def index():
    if 'username' not in session: return redirect(url_for('login'))
    recent_foods = session.get('recent_foods', [])
    return render_template("upload.html", recent_foods=recent_foods)

@app.route('/video')
def video():
    """웹캠 페이지입니다. 로그인해야 접근 가능합니다."""
    if 'username' not in session:
        return redirect(url_for('login'))
    return render_template('video.html')

@app.route('/video_feed')
def video_feed():
    if 'username' not in session:
        return redirect(url_for('login'))
    return Response(generate_frames(), mimetype='multipart/x-mixed-replace; boundary=frame')

def process_and_annotate_image(source_path):
    """이미지 경로를 받아 객체 탐지 및 바운딩 박스 그리기를 수행하고 결과 정보를 반환합니다."""
    results_yolo = model.predict(source_path)
    
    # 중복을 제거한 음식 이름 목록 추출
    detected_food_names = sorted(list(set([names[int(box.cls[0].item())] for box in results_yolo[0].boxes])))
    
    img = Image.open(source_path).convert("RGB")
    draw = ImageDraw.Draw(img)
    df = pd.read_csv(CSV_PATH)
    try:
        font = ImageFont.truetype("NanumGothic.ttf", 30)
    except IOError:
        font = ImageFont.load_default()

    for box in results_yolo[0].boxes:
        cls_id = int(box.cls[0].item())
        x1, y1, x2, y2 = map(int, box.xyxy[0].tolist())
        food_name = names[cls_id]
        row = df[df['음식'] == food_name]
        calorie = float(row.iloc[0].get("kcal", 0)) if not row.empty else 0
        color = get_color_by_calorie(calorie)
        draw.rectangle([x1, y1, x2, y2], outline=color, width=3)
        draw.text((x1, y1 - 20), food_name, font=font, fill=color)
        
    result_filename = f"result_{uuid.uuid4().hex[:8]}.jpg"
    result_path = os.path.join('static', RESULT_FOLDER, result_filename)
    img.save(result_path)
    
    # 웹 경로를 위해 역슬래시(\)를 슬래시(/)로 변환
    web_path = os.path.join(RESULT_FOLDER, result_filename).replace('\\', '/')
    return detected_food_names, web_path


@app.route('/upload', methods=['POST'])
def upload():
    if 'username' not in session: return redirect(url_for('login'))
    file = request.files.get('file')
    if not file or file.filename == '':
        flash("파일이 없습니다.")
        return redirect(url_for('index'))
        
    filepath = os.path.join('static', UPLOAD_FOLDER, file.filename)
    file.save(filepath)
    
    # 중앙 처리 함수를 호출하여 분석 및 결과 이미지 생성
    detected_foods, result_image_path = process_and_annotate_image(filepath)
    
    if not detected_foods:
        flash("이미지에서 음식을 찾을 수 없습니다. 다른 사진으로 시도해보세요.")
        return redirect(url_for('index'))

    # 세션에 정확한 결과 이미지 경로 저장
    session['detected_foods'] = detected_foods
    session['result_image'] = result_image_path
    print(f"✅ 2단계: 세션에 저장된 이미지 경로는 -> {session['result_image']}")

    # 양 조절 페이지로 이동
    return redirect(url_for('adjust_quantity'))

@app.route('/capture_and_process', methods=['POST'])
def capture_and_process():
    if 'username' not in session: return jsonify({'success': False, 'message': '로그인이 필요합니다.'}), 401
    if camera is None or not camera.isOpened(): return jsonify({'success': False, 'message': '웹캠을 사용할 수 없습니다.'}), 500

    ret, frame = camera.read()
    if not ret: return jsonify({'success': False, 'message': '웹캠 프레임 캡처 실패'}), 500
    
    filepath = os.path.join('static', UPLOAD_FOLDER, f"capture_{uuid.uuid4().hex[:8]}.jpg")
    cv2.imwrite(filepath, frame)

    # 중앙 처리 함수를 호출하여 분석 및 결과 이미지 생성
    detected_foods, result_image_path = process_and_annotate_image(filepath)

    if not detected_foods:
        return jsonify({'success': False, 'message': '이미지에서 음식을 찾을 수 없습니다.'})
        
    # 세션에 정확한 결과 이미지 경로 저장
    session['detected_foods'] = detected_foods
    session['result_image'] = result_image_path

    # 양 조절 페이지로 이동하는 URL을 반환
    return jsonify({'success': True, 'redirect_url': url_for('adjust_quantity')})



# ★★★★★ 신규 추가된 라우트 ★★★★★
@app.route('/adjust_quantity')
def adjust_quantity():
    """인식된 음식의 단위에 맞춰 양을 조절하는 페이지를 렌더링합니다."""
    if 'username' not in session: return redirect(url_for('login'))

    detected_foods = session.get('detected_foods')
    result_image = session.get('result_image')
    print(f"✅ 3단계: 다음 페이지로 전달되는 이미지 경로는 -> {result_image}")

    if not detected_foods or not result_image:
        flash("분석할 음식 정보가 없습니다. 다시 시도해주세요.")
        return redirect(url_for('index'))
    
    # CSV에서 각 음식의 단위를 찾아 함께 전달
    df = pd.read_csv(CSV_PATH)
    foods_with_units = []
    for food_name in detected_foods:
        row = df[df['음식'] == food_name]
        if not row.empty:
            unit = row.iloc[0]['단위']
            foods_with_units.append({'name': food_name, 'unit': unit})
        else:
            # CSV에 정보가 없는 경우 기본 단위 '인분' 사용
            foods_with_units.append({'name': food_name, 'unit': '인분'})

    return render_template('adjust_quantity.html', foods_with_units=foods_with_units, result_image=result_image)


@app.route('/calculate_results', methods=['POST'])
def calculate_results():
    """사용자가 입력한 양과 기준값에 맞춰 영양 정보를 계산하고 최종 결과 페이지로 리디렉션합니다."""
    if 'username' not in session: return redirect(url_for('login'))

    quantities = request.form
    detected_foods_from_session = session.get('detected_foods', [])
    df = pd.read_csv(CSV_PATH)
    results = []

    # 최근 음식 기록 업데이트
    recent_foods_deque = collections.deque(session.get('recent_foods', []), maxlen=3)
    for food_name in detected_foods_from_session:
        if food_name not in recent_foods_deque:
            recent_foods_deque.appendleft(food_name)
    session['recent_foods'] = list(recent_foods_deque)

    for food_name in detected_foods_from_session:
        user_quantity = float(quantities.get(food_name, 0)) # 사용자가 입력한 양
        row = df[df['음식'] == food_name]
        
        if not row.empty:
            base_info = row.iloc[0]
            base_quantity = float(base_info.get('기준값', 1.0)) # CSV의 기준값 (예: 100)
            unit = base_info.get('단위', '인분')
            
            # 계산 비율 = (사용자 입력값 / CSV 기준값)
            ratio = user_quantity / base_quantity
            
            adjusted_info = {
                'quantity': user_quantity, # 사용자가 입력한 값
                'unit': unit              # 단위
            }
            
            # 숫자 형태의 영양 정보만 비율에 맞춰 계산
            for key, value in base_info.items():
                try:
                    numeric_value = float(value)
                    adjusted_info[key] = round(numeric_value * ratio, 2)
                except (ValueError, TypeError):
                    adjusted_info[key] = value # 텍스트 정보는 그대로 유지
            
            results.append({"name": food_name, "info": adjusted_info})
        else:
            results.append({"name": food_name, "info": None})

    session['results'] = results
    session.pop('detected_foods', None)
    
    return redirect(url_for('show_results'))


@app.route('/results')
def show_results():
    if 'username' not in session: return redirect(url_for('login'))
    results = session.get('results')
    result_image = session.get('result_image')
    if not results or not result_image:
        flash("결과를 표시할 정보가 없습니다.")
        return redirect(url_for('index'))
        
    today_date = datetime.now().strftime('%Y-%m-%d')
    return render_template('result_with_bbox.html', results=results, result_image=result_image, today_date=today_date)
                           
# ★★★ 수정된 라우트: BMR 및 잔여 칼로리 계산 로직 추가 ★★★
@app.route('/journal', methods=['GET'])
def journal_calendar():
    if 'username' not in session:
        return redirect(url_for('login'))
    
    username = session['username']
    today_date_str = datetime.now().strftime('%Y-%m-%d') # 오늘 날짜를 기본값으로 사용

    year = request.args.get('year', type=int, default=datetime.now().year)
    month = request.args.get('month', type=int, default=datetime.now().month)
    
    # 캘린더 표시를 위해 선택된 날짜 (달력에서 날짜를 선택했다면 그 날짜를 기준으로 잔여 칼로리 표시 가능)
    # 현재는 단순화를 위해 오늘 날짜를 기준으로 잔여 칼로리를 계산합니다.
    selected_date_str = request.args.get('date', today_date_str) 

    current_date = datetime(year, month, 1)
    
    prev_month_date = current_date - timedelta(days=1)
    prev_year, prev_month = prev_month_date.year, prev_month_date.month
    
    # 다음 달 계산 (월이 12월을 넘어가면 해를 1 증가시키고 월을 1로)
    next_month = month + 1
    next_year = year
    if next_month > 12:
        next_month = 1
        next_year += 1
        
    # 1. BMR 및 잔여 칼로리 계산
    users = load_user_data()
    user_bmr = users.get(username, {}).get('bmr', 0) 
    
    remaining_calories = calculate_daily_remaining_calories(username, selected_date_str)

    # 2. 저널 데이터 로드
    journal_data = load_journal_data()

    # 3. 템플릿 렌더링
    return render_template('journal_calendar.html', 
                           year=year, month=month, journal_data=journal_data,
                           prev_year=prev_year, prev_month=prev_month,
                           next_year=next_year, next_month=next_month,
                           # ★★★ 새로 추가된 변수 ★★★
                           user_bmr=user_bmr,
                           remaining_calories=remaining_calories)
# ★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★

# 이 라우트는 journal_entry.html에서 사진을 바로 업로드/분석할 때 사용되므로 유지합니다.
@app.route('/journal/upload/<string:date_str>', methods=['POST'])
def upload_for_journal(date_str):
    if 'username' not in session:
        return redirect(url_for('login'))
        
    file = request.files.get('file')
    if not file:
        flash("파일이 선택되지 않았습니다.")
        return redirect(url_for('journal_entry', date_str=date_str))

    # (이하 로직은 /upload와 거의 동일, 세션에 결과를 저장하고 journal_entry로 리디렉션)
    filename = file.filename
    filepath = os.path.join('static', UPLOAD_FOLDER, filename)
    file.save(filepath)
    results_yolo = model.predict(filepath)
    df = pd.read_csv(CSV_PATH)
    detected_food_names = [names[int(box.cls[0].item())] for box in results_yolo[0].boxes]
    food_counts = collections.Counter(detected_food_names)
    results = []
    
    for food_name, count in food_counts.items():
        row = df[df['음식'] == food_name]
        food_info = row.iloc[0].to_dict() if not row.empty else None
        if food_info:
            food_info['count'] = count
            results.append({"name": food_name, "info": food_info})

    # 세션에 임시 결과 저장
    session['results'] = results
    # 임시 결과 이미지는 분석 후 journal에 저장될 것이므로 result 폴더에 저장
    session['result_image'] = f'results/temp_{uuid.uuid4()}.jpg' 
    # (코드 간결성을 위해 경계상자 그리는 부분은 save_journal_entry에서 처리)
    
    return redirect(url_for('journal_entry', date_str=date_str))


@app.route('/journal/entry/<string:date_str>')
def journal_entry(date_str):
    if 'username' not in session:
        return redirect(url_for('login'))
        
    journal_data = load_journal_data()
    daily_entries_data = journal_data.get(date_str, {}).get('entries', [])
    
    temp_entry = None
    if 'results' in session and 'result_image' in session:
        temp_entry = {
            'content': '',
            'image': session.get('result_image'),
            'results': session.get('results')
        }
    
    return render_template('journal_entry.html', 
                           date=date_str, 
                           daily_entries=daily_entries_data,
                           temp_entry=temp_entry)

@app.route('/save_journal_entry', methods=['POST'])
def save_journal_entry():
    if 'username' not in session: return redirect(url_for('login'))
        
    date = request.form.get('date')
    content = request.form.get('content')
    journal_data = load_journal_data()
    
    image_url, results_to_save = None, []
    file = request.files.get('file')

    # 1. 기록 일지에서 직접 파일을 업로드한 경우
    if file and file.filename != '':
        filename_base = f"journal_{date}_{uuid.uuid4().hex[:8]}"
        original_filepath = os.path.join('static', UPLOAD_FOLDER, f"{filename_base}.jpg")
        file.save(original_filepath)
        
        # 분석 로직은 process_and_annotate_image 함수를 재사용
        detected_foods, annotated_image_path = process_and_annotate_image(original_filepath)
        
        # 분석 결과를 기반으로 results_to_save 리스트 생성
        df = pd.read_csv(CSV_PATH)
        for food_name in detected_foods:
            row = df[df['음식'] == food_name]
            if not row.empty:
                food_info = row.iloc[0].to_dict()
                # ★★★ 여기서 quantity와 unit을 기본값으로 생성 ★★★
                food_info['quantity'] = 1 
                food_info['unit'] = row.iloc[0].get('단위', '개')
                results_to_save.append({'name': food_name, 'info': food_info})

        # 분석된 이미지를 영구 저장 위치로 복사
        final_image_name = f"journal_{date}_{uuid.uuid4().hex[:8]}_result.jpg"
        final_image_path = os.path.join('static', 'journal_images', final_image_name)
        shutil.copy(os.path.join('static', annotated_image_path), final_image_path)
        image_url = os.path.join('journal_images', final_image_name).replace('\\', '/')

    # 2. 메인 분석 프로세스를 거쳐 온 경우
    elif 'result_image' in session and 'results' in session:
        results_to_save = session.pop('results', [])
        temp_image_path = session.pop('result_image', None)
        temp_full_path = os.path.join('static', temp_image_path)

        if temp_image_path and os.path.exists(temp_full_path):
            filename = f"journal_{date}_{uuid.uuid4().hex[:8]}.jpg"
            new_full_path = os.path.join('static', 'journal_images', filename)
            shutil.copy(temp_full_path, new_full_path)
            image_url = os.path.join('journal_images', filename).replace('\\', '/')
    
    # 3. 최종적으로 저널 데이터에 저장
    if image_url or content:
        if date not in journal_data: journal_data[date] = {'entries': []}
        
        new_entry = {
            'id': str(uuid.uuid4()),
            'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'), 
            'content': content, 
            'image': image_url, 
            'results': results_to_save
        }
        
        if 'entries' not in journal_data[date]: journal_data[date]['entries'] = []
        journal_data[date]['entries'].insert(0, new_entry) 
        save_journal_data(journal_data)

    return redirect(url_for('journal_calendar'))


@app.route('/delete_journal_entry/<string:date_str>', methods=['POST'])
def delete_journal_entry_all(date_str):
    if 'username' not in session:
        return jsonify({'success': False, 'message': '로그인이 필요합니다.'}), 401
        
    journal_data = load_journal_data()
    
    if date_str in journal_data:
        for entry in journal_data[date_str].get('entries', []):
            if entry.get('image'):
                try:
                    os.remove(os.path.join('static', entry['image']))
                except FileNotFoundError:
                    pass
                    
        del journal_data[date_str]
        save_journal_data(journal_data)
        
    return jsonify({'success': True})

@app.route('/discard_entry')
def discard_entry_and_go_back():
    temp_image_path = session.pop('result_image', None)
    if temp_image_path:
        try:
            os.remove(os.path.join('static', temp_image_path))
        except FileNotFoundError:
            pass
    session.pop('results', None)
    # 날짜 정보가 없으므로 메인 캘린더로 이동
    return redirect(url_for('journal_calendar'))

@app.route('/discard_results')
def discard_results_and_go_home():
    temp_image_path = session.pop('result_image', None)
    session.pop('results', None)
    
    if temp_image_path:
        try:
            full_path = os.path.join(app.root_path, 'static', temp_image_path)
            if os.path.exists(full_path):
                os.remove(full_path)
        except FileNotFoundError:
            pass
            
    return redirect(url_for('index'))

@app.route('/delete_journal_entry/<string:date_str>/<string:entry_id>', methods=['POST'])
def delete_single_entry(date_str, entry_id):
    if 'username' not in session:
        return jsonify({'success': False, 'message': '로그인이 필요합니다.'}), 401

    journal_data = load_journal_data()
    
    if date_str in journal_data and 'entries' in journal_data[date_str]:
        entries = journal_data[date_str]['entries']
        
        entry_to_delete = next((e for e in entries if e.get('id') == entry_id), None)
        
        if entry_to_delete:
            if entry_to_delete.get('image'):
                try:
                    os.remove(os.path.join('static', entry_to_delete['image']))
                except FileNotFoundError:
                    pass
            
            journal_data[date_str]['entries'].remove(entry_to_delete)
            
            if not journal_data[date_str]['entries']:
                del journal_data[date_str]
                
            save_journal_data(journal_data)
            return jsonify({'success': True})

    return jsonify({'success': False, 'message': '기록을 찾을 수 없습니다.'})
"""
@app.route('/debug_session')
def debug_session():
    
    # 현재 Flask 세션의 모든 내용을 JSON 형태로 출력하는 디버그 라우트입니다.
    # 실제 서비스 환경에서는 보안상의 이유로 반드시 제거하거나 로그인된 관리자만 접근하도록 설정해야 합니다.
    
    if 'username' not in session:
        # 로그인된 사용자에게만 정보를 보여주는 것이 일반적입니다.
        return jsonify({"message": "로그인이 필요합니다."}), 401
        
    # session 객체는 딕셔너리와 같으므로, 직접 복사하여 JSON 형태로 반환할 수 있습니다.
    session_data = dict(session)
    
    # 가독성을 높이기 위해 JSON 형태로 반환합니다.
    return jsonify({
        "current_user": session.get('username'),
        "session_data": session_data
    })
"""
if __name__ == "__main__":
    app.run(host="0.0.0.0", debug=True)