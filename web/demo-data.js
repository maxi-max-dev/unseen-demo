// 由 tools/build_demo_data.py 从 server/spaces/s4/space.json 自动导出, 不要手改。
// 重跑: python3 tools/build_demo_data.py
window.DEMO_DATA = {
  "generatedFrom": "server/spaces/s4/space.json",
  "spaceId": "s4",
  "spaceTitle": "阈值验证空间",
  "nodeName": "宴会厅",
  "nodeTime": "18:00",
  "pano": "demo-assets/pano.jpg",
  "stats": {
    "total": 11,
    "auto": 7,
    "review": 4,
    "approved": 0,
    "rejected": 0,
    "tasksTotal": 7,
    "tasksOpen": 2,
    "tasksFilled": 5,
    "confMin": 0.82,
    "marginMin": 0.055
  },
  "photos": [
    {
      "id": "p1",
      "img": "demo-assets/ph_p1.jpg",
      "yaw": 344.6,
      "confidence": 0.9158,
      "margin": 0.1019,
      "state": "auto_ok",
      "reason": "匹配度 0.92、辨识度 0.102,两项都达标,自动入选",
      "contributor": "小明",
      "taskId": "t1",
      "bearing": "正前方"
    },
    {
      "id": "p2",
      "img": "demo-assets/ph_p2.jpg",
      "yaw": 15.1,
      "confidence": 0.8793,
      "margin": 0.0759,
      "state": "auto_ok",
      "reason": "匹配度 0.88、辨识度 0.076,两项都达标,自动入选",
      "contributor": "小明",
      "taskId": null,
      "bearing": "正前方"
    },
    {
      "id": "p3",
      "img": "demo-assets/ph_p3.jpg",
      "yaw": 105.0,
      "confidence": 0.7844,
      "margin": 0.015,
      "state": "needs_review",
      "reason": "匹配度 0.78 偏低,辨识度 0.015 也偏低 —— 这张很可能不是在这个空间拍的,请你看一眼",
      "contributor": "小明",
      "taskId": null,
      "bearing": "右侧"
    },
    {
      "id": "p4",
      "img": "demo-assets/ph_p4.jpg",
      "yaw": 194.9,
      "confidence": 0.9191,
      "margin": 0.066,
      "state": "auto_ok",
      "reason": "匹配度 0.92、辨识度 0.066,两项都达标,自动入选",
      "contributor": "小红",
      "taskId": "t2",
      "bearing": "正后方"
    },
    {
      "id": "p5",
      "img": "demo-assets/ph_p5.jpg",
      "yaw": 74.5,
      "confidence": 0.6022,
      "margin": 0.0488,
      "state": "needs_review",
      "reason": "匹配度 0.60 偏低,辨识度 0.049 也偏低 —— 这张很可能不是在这个空间拍的,请你看一眼",
      "contributor": "阿伟",
      "taskId": null,
      "bearing": "右侧"
    },
    {
      "id": "p6",
      "img": "demo-assets/ph_p6.jpg",
      "yaw": 225.0,
      "confidence": 0.8824,
      "margin": 0.0675,
      "state": "auto_ok",
      "reason": "匹配度 0.88、辨识度 0.068,两项都达标,自动入选",
      "contributor": "匿名宾客",
      "taskId": "t3",
      "bearing": "左后方"
    },
    {
      "id": "p8",
      "img": "demo-assets/ph_p8.jpg",
      "yaw": 255.3,
      "confidence": 0.8933,
      "margin": 0.0719,
      "state": "auto_ok",
      "reason": "匹配度 0.89、辨识度 0.072,两项都达标,自动入选",
      "contributor": "大伟",
      "taskId": "t5",
      "bearing": "左侧"
    },
    {
      "id": "p9",
      "img": "demo-assets/ph_p9.jpg",
      "yaw": 255.3,
      "confidence": 0.8933,
      "margin": 0.0719,
      "state": "auto_ok",
      "reason": "匹配度 0.89、辨识度 0.072,两项都达标,自动入选",
      "contributor": "匿名宾客",
      "taskId": null,
      "bearing": "左侧"
    },
    {
      "id": "p10",
      "img": "demo-assets/ph_p10.jpg",
      "yaw": 104.9,
      "confidence": 0.5583,
      "margin": 0.0272,
      "state": "needs_review",
      "reason": "匹配度 0.56 偏低,辨识度 0.027 也偏低 —— 这张很可能不是在这个空间拍的,请你看一眼",
      "contributor": "匿名宾客",
      "taskId": "t4",
      "bearing": "右侧"
    },
    {
      "id": "p11",
      "img": "demo-assets/ph_p11.jpg",
      "yaw": 165.0,
      "confidence": 0.9144,
      "margin": 0.0562,
      "state": "auto_ok",
      "reason": "匹配度 0.91、辨识度 0.056,两项都达标,自动入选",
      "contributor": "匿名宾客",
      "taskId": "t4",
      "bearing": "正后方"
    },
    {
      "id": "p12",
      "img": "demo-assets/ph_p12.jpg",
      "yaw": 255.4,
      "confidence": 0.5319,
      "margin": 0.0277,
      "state": "needs_review",
      "reason": "匹配度 0.53 偏低,辨识度 0.028 也偏低 —— 这张很可能不是在这个空间拍的,请你看一眼",
      "contributor": "匿名宾客",
      "taskId": "t6",
      "bearing": "左侧"
    }
  ],
  "hero": {
    "photo": {
      "id": "p1",
      "img": "demo-assets/ph_p1.jpg",
      "yaw": 344.6,
      "confidence": 0.9158,
      "margin": 0.1019,
      "state": "auto_ok",
      "reason": "匹配度 0.92、辨识度 0.102,两项都达标,自动入选",
      "contributor": "小明",
      "taskId": "t1",
      "bearing": "正前方"
    },
    "task": {
      "id": "t1",
      "title": "缺这个角度",
      "brief": "站在原地转向正前方,拍那个方向",
      "yaw": 0,
      "yawRange": [
        300,
        59
      ],
      "bounty": 50,
      "img": "demo-assets/task_t1.jpg"
    }
  },
  "trio": [
    {
      "id": "p2",
      "img": "demo-assets/ph_p2.jpg",
      "yaw": 15.1,
      "confidence": 0.8793,
      "margin": 0.0759,
      "state": "auto_ok",
      "reason": "匹配度 0.88、辨识度 0.076,两项都达标,自动入选",
      "contributor": "小明",
      "taskId": null,
      "bearing": "正前方"
    },
    {
      "id": "p4",
      "img": "demo-assets/ph_p4.jpg",
      "yaw": 194.9,
      "confidence": 0.9191,
      "margin": 0.066,
      "state": "auto_ok",
      "reason": "匹配度 0.92、辨识度 0.066,两项都达标,自动入选",
      "contributor": "小红",
      "taskId": "t2",
      "bearing": "正后方"
    },
    {
      "id": "p8",
      "img": "demo-assets/ph_p8.jpg",
      "yaw": 255.3,
      "confidence": 0.8933,
      "margin": 0.0719,
      "state": "auto_ok",
      "reason": "匹配度 0.89、辨识度 0.072,两项都达标,自动入选",
      "contributor": "大伟",
      "taskId": "t5",
      "bearing": "左侧"
    }
  ],
  "wall": [
    {
      "id": "t1",
      "type": "gap",
      "title": "缺这个角度",
      "brief": "站在原地转向正前方,拍那个方向",
      "yaw": 0,
      "yawRange": [
        300,
        59
      ],
      "bounty": 50,
      "status": "filled",
      "filledBy": [
        "小明"
      ],
      "img": "demo-assets/task_t1.jpg",
      "fills": [
        {
          "id": "p1",
          "img": "demo-assets/ph_p1.jpg",
          "yaw": 344.6,
          "confidence": 0.9158,
          "margin": 0.1019,
          "state": "auto_ok",
          "reason": "匹配度 0.92、辨识度 0.102,两项都达标,自动入选",
          "contributor": "小明",
          "taskId": "t1",
          "bearing": "正前方"
        }
      ],
      "bearing": "正前方"
    },
    {
      "id": "t2",
      "type": "gap",
      "title": "缺这个角度",
      "brief": "站在原地转向右后方,拍那个方向",
      "yaw": 120,
      "yawRange": [
        60,
        179
      ],
      "bounty": 50,
      "status": "filled",
      "filledBy": [
        "小红"
      ],
      "img": "demo-assets/task_t2.jpg",
      "fills": [
        {
          "id": "p4",
          "img": "demo-assets/ph_p4.jpg",
          "yaw": 194.9,
          "confidence": 0.9191,
          "margin": 0.066,
          "state": "auto_ok",
          "reason": "匹配度 0.92、辨识度 0.066,两项都达标,自动入选",
          "contributor": "小红",
          "taskId": "t2",
          "bearing": "正后方"
        }
      ],
      "bearing": "右后方"
    },
    {
      "id": "t3",
      "type": "gap",
      "title": "缺这个角度",
      "brief": "站在原地转向左后方,拍那个方向",
      "yaw": 240,
      "yawRange": [
        180,
        299
      ],
      "bounty": 50,
      "status": "filled",
      "filledBy": [
        "匿名宾客"
      ],
      "img": "demo-assets/task_t3.jpg",
      "fills": [
        {
          "id": "p6",
          "img": "demo-assets/ph_p6.jpg",
          "yaw": 225.0,
          "confidence": 0.8824,
          "margin": 0.0675,
          "state": "auto_ok",
          "reason": "匹配度 0.88、辨识度 0.068,两项都达标,自动入选",
          "contributor": "匿名宾客",
          "taskId": "t3",
          "bearing": "左后方"
        }
      ],
      "bearing": "左后方"
    },
    {
      "id": "t4",
      "type": "gap",
      "title": "缺这个角度",
      "brief": "站在原地转向右侧,拍那个方向",
      "yaw": 105,
      "yawRange": [
        36,
        174
      ],
      "bounty": 50,
      "status": "filled",
      "filledBy": [
        "匿名宾客"
      ],
      "img": "demo-assets/task_t4.jpg",
      "fills": [
        {
          "id": "p10",
          "img": "demo-assets/ph_p10.jpg",
          "yaw": 104.9,
          "confidence": 0.5583,
          "margin": 0.0272,
          "state": "needs_review",
          "reason": "匹配度 0.56 偏低,辨识度 0.027 也偏低 —— 这张很可能不是在这个空间拍的,请你看一眼",
          "contributor": "匿名宾客",
          "taskId": "t4",
          "bearing": "右侧"
        },
        {
          "id": "p11",
          "img": "demo-assets/ph_p11.jpg",
          "yaw": 165.0,
          "confidence": 0.9144,
          "margin": 0.0562,
          "state": "auto_ok",
          "reason": "匹配度 0.91、辨识度 0.056,两项都达标,自动入选",
          "contributor": "匿名宾客",
          "taskId": "t4",
          "bearing": "正后方"
        }
      ],
      "bearing": "右侧"
    },
    {
      "id": "t5",
      "type": "gap",
      "title": "缺这个角度",
      "brief": "站在原地转向左侧,拍那个方向",
      "yaw": 285,
      "yawRange": [
        246,
        324
      ],
      "bounty": 50,
      "status": "filled",
      "filledBy": [
        "大伟"
      ],
      "img": "demo-assets/task_t5.jpg",
      "fills": [
        {
          "id": "p8",
          "img": "demo-assets/ph_p8.jpg",
          "yaw": 255.3,
          "confidence": 0.8933,
          "margin": 0.0719,
          "state": "auto_ok",
          "reason": "匹配度 0.89、辨识度 0.072,两项都达标,自动入选",
          "contributor": "大伟",
          "taskId": "t5",
          "bearing": "左侧"
        }
      ],
      "bearing": "左侧"
    },
    {
      "id": "t6",
      "type": "gap",
      "title": "缺这个角度",
      "brief": "站在原地转向左前方,拍那个方向",
      "yaw": 300,
      "yawRange": [
        276,
        324
      ],
      "bounty": 50,
      "status": "open",
      "filledBy": [],
      "img": "demo-assets/task_t6.jpg",
      "fills": [
        {
          "id": "p12",
          "img": "demo-assets/ph_p12.jpg",
          "yaw": 255.4,
          "confidence": 0.5319,
          "margin": 0.0277,
          "state": "needs_review",
          "reason": "匹配度 0.53 偏低,辨识度 0.028 也偏低 —— 这张很可能不是在这个空间拍的,请你看一眼",
          "contributor": "匿名宾客",
          "taskId": "t6",
          "bearing": "左侧"
        }
      ],
      "bearing": "左前方"
    },
    {
      "id": "t7",
      "type": "gap",
      "title": "缺这个角度",
      "brief": "站在原地转向右侧,拍那个方向",
      "yaw": 90,
      "yawRange": [
        36,
        144
      ],
      "bounty": 50,
      "status": "open",
      "filledBy": [],
      "img": "demo-assets/task_t7.jpg",
      "fills": [],
      "bearing": "右侧"
    }
  ],
  "needsReview": [
    {
      "id": "p3",
      "img": "demo-assets/ph_p3.jpg",
      "yaw": 105.0,
      "confidence": 0.7844,
      "margin": 0.015,
      "state": "needs_review",
      "reason": "匹配度 0.78 偏低,辨识度 0.015 也偏低 —— 这张很可能不是在这个空间拍的,请你看一眼",
      "contributor": "小明",
      "taskId": null,
      "bearing": "右侧"
    },
    {
      "id": "p5",
      "img": "demo-assets/ph_p5.jpg",
      "yaw": 74.5,
      "confidence": 0.6022,
      "margin": 0.0488,
      "state": "needs_review",
      "reason": "匹配度 0.60 偏低,辨识度 0.049 也偏低 —— 这张很可能不是在这个空间拍的,请你看一眼",
      "contributor": "阿伟",
      "taskId": null,
      "bearing": "右侧"
    },
    {
      "id": "p10",
      "img": "demo-assets/ph_p10.jpg",
      "yaw": 104.9,
      "confidence": 0.5583,
      "margin": 0.0272,
      "state": "needs_review",
      "reason": "匹配度 0.56 偏低,辨识度 0.027 也偏低 —— 这张很可能不是在这个空间拍的,请你看一眼",
      "contributor": "匿名宾客",
      "taskId": "t4",
      "bearing": "右侧"
    },
    {
      "id": "p12",
      "img": "demo-assets/ph_p12.jpg",
      "yaw": 255.4,
      "confidence": 0.5319,
      "margin": 0.0277,
      "state": "needs_review",
      "reason": "匹配度 0.53 偏低,辨识度 0.028 也偏低 —— 这张很可能不是在这个空间拍的,请你看一眼",
      "contributor": "匿名宾客",
      "taskId": "t6",
      "bearing": "左侧"
    }
  ],
  "calibration": {
    "note": "阈值标定实测(24 张标定集)",
    "total": 24,
    "correct": 23,
    "foreignTotal": 15,
    "foreignBlocked": 15,
    "confMin": 0.82,
    "marginMin": 0.055
  }
};
