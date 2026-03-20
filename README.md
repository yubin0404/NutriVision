# 🥗 NutriVision (AI 기반 식단 영양 분석 웹 서비스)

## 프로젝트 개요
사용자가 사진이나 카메라를 통해 음식 사진을 업로드하면 인공지능(YOLOv8s)이 이미지를 분석하여 음식의 종류를 인식하고 해당 음식의 영양성분(칼로리, 탄수화물, 단백질 등)을 웹 화면에 제공하는 Flask 기반 AI 기반 웹 서비스입니다.

## 기술 스택
* **Backend:** Python, Flask
* **AI:** YOLOv8s
* **Frontend:** HTML, CSS - templates
* **Data:** 직접 구현한 20종류의 음식 이미지 데이터, CSV

## 파일 구조
* `food_test_H.py` : **[Main APP]** Flask 웹 서버를 구동하고 사용자의 이미지 업로드 창부터 YOLO 모델 초론 결과까지 전체 흐름을 제어하는 메인 파이썬 코드입니다.
* 


