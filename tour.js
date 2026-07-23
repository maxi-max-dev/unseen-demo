// tour.js -- 空间记忆 tour 数据契约(冻结版)。
// 用 <script> 标签加载,挂到 window.TOUR,绕开 file:// 下的 XHR/fetch 限制。
// 2026-07-23 主题改版:demo 场景从 AdventureX 会场切换为「中国传统婚礼旅程」。
// 本文件当前内容 = 合成测试素材(tools/fixtures.py 生成),真实影石全景到位后替换 assets 图片
// 并用真实照片重新填 photos 数组即可,结构不变。
// journey:true 时,链接热点文案会用 nodes 数组顺序推「下一站」(见 viewer/index.html)。
// 2026-07-23 在线增强版(viewer/online.html)追加字段(追加式,不改现有结构):
//   - 每个 node 加 "geo":{lng,lat} = 高德坐标(GCJ-02)
//   - 顶层加 "geoRoute" = 婚车路线途经点数组
// 路线选杭州"未来科技城→紫金港路→天目山路→西溪湿地"一带真实道路走向做示意:
// 新娘家落在未来科技城文一西路附近小区,车队东行转紫金港路南下再转天目山路,
// 抵达西溪湿地边的酒店(仪式/宴席同园区不同楼)。坐标为合理近似值,真实素材到位后替换。
window.TOUR = {
  "meta": {
    "title": "空间记忆",
    "version": 2
  },
  "journey": true,
  "map": {
    "image": "assets/map/journey.jpg",
    "width": 2048,
    "height": 1536
  },
  "geoRoute": [
    [
      120.0057,
      30.279
    ],
    [
      120.0125,
      30.2799
    ],
    [
      120.0198,
      30.2803
    ],
    [
      120.0271,
      30.2801
    ],
    [
      120.0276,
      30.27
    ],
    [
      120.029,
      30.258
    ],
    [
      120.041,
      30.252
    ],
    [
      120.062,
      30.247
    ]
  ],
  "nodes": [
    {
      "id": "jieqin",
      "name": "新娘家",
      "sub": "新娘家 · 堵门红包",
      "chapter": "接亲",
      "time": "09:08",
      "panorama": "assets/panos/jieqin.jpg",
      "map": {
        "x": 0.13,
        "y": 0.8
      },
      "geo": {
        "lng": 120.0057,
        "lat": 30.279
      },
      "photos": [
        {
          "src": "assets/photos/w001.jpg",
          "yaw": 51,
          "pitch": 7,
          "confidence": 1.0,
          "by": "manual",
          "caption": "堵门红包"
        },
        {
          "src": "assets/photos/w002.jpg",
          "yaw": 75.2,
          "pitch": 0,
          "confidence": 0.8745,
          "by": "auto",
          "caption": "伴娘团合影"
        },
        {
          "src": "assets/photos/w003.jpg",
          "yaw": 285.4,
          "pitch": 0,
          "confidence": 0.8683,
          "by": "auto",
          "caption": "藏婚鞋"
        },
        {
          "src": "assets/photos/w004.jpg",
          "yaw": 164.6,
          "pitch": 0,
          "confidence": 0.8956,
          "by": "auto",
          "caption": "敬茶改口"
        },
        {
          "src": "assets/photos/w005.jpg",
          "yaw": 194.9,
          "pitch": 0,
          "confidence": 0.8708,
          "by": "auto",
          "caption": "红包雨"
        },
        {
          "src": "assets/photos/w006.jpg",
          "yaw": 45.0,
          "pitch": 0,
          "confidence": 0.8435,
          "by": "auto",
          "caption": "伴娘拦门"
        },
        {
          "src": "assets/photos/w007.jpg",
          "yaw": 255.1,
          "pitch": 0,
          "confidence": 0.9328,
          "by": "auto",
          "caption": "找鞋游戏"
        },
        {
          "src": "assets/photos/w008.jpg",
          "yaw": 164.6,
          "pitch": 0,
          "confidence": 0.8273,
          "by": "auto",
          "caption": "新娘化妆"
        },
        {
          "src": "assets/photos/w009.jpg",
          "yaw": 314.7,
          "pitch": 0,
          "confidence": 0.8738,
          "by": "auto",
          "caption": "姐妹团送嫁"
        },
        {
          "src": "assets/photos/w010.jpg",
          "yaw": 314.8,
          "pitch": 0,
          "confidence": 0.8937,
          "by": "auto",
          "caption": "新郎闯关"
        },
        {
          "src": "assets/photos/w020.jpg",
          "yaw": 315.2,
          "pitch": 0,
          "confidence": 0.793,
          "by": "auto",
          "caption": "出门爆竹"
        }
      ]
    },
    {
      "id": "chufa",
      "name": "出发",
      "sub": "婚车头车 · 车队过城",
      "chapter": "出发",
      "time": "10:30",
      "panorama": "assets/panos/chufa.jpg",
      "map": {
        "x": 0.46,
        "y": 0.6
      },
      "geo": {
        "lng": 120.0271,
        "lat": 30.2801
      },
      "photos": [
        {
          "src": "assets/photos/w011.jpg",
          "yaw": 12,
          "pitch": 9,
          "confidence": 1.0,
          "by": "manual",
          "caption": "婚车头车"
        },
        {
          "src": "assets/photos/w012.jpg",
          "yaw": 45.0,
          "pitch": 0,
          "confidence": 0.8744,
          "by": "auto",
          "caption": "车队出发"
        },
        {
          "src": "assets/photos/w013.jpg",
          "yaw": 194.9,
          "pitch": 0,
          "confidence": 0.9452,
          "by": "auto",
          "caption": "头车红花"
        },
        {
          "src": "assets/photos/w014.jpg",
          "yaw": 225.0,
          "pitch": 0,
          "confidence": 0.9044,
          "by": "auto",
          "caption": "沿途鸣笛"
        },
        {
          "src": "assets/photos/w015.jpg",
          "yaw": 194.9,
          "pitch": 0,
          "confidence": 0.8636,
          "by": "auto",
          "caption": "车队过桥"
        },
        {
          "src": "assets/photos/w016.jpg",
          "yaw": 104.9,
          "pitch": 0,
          "confidence": 0.8971,
          "by": "auto",
          "caption": "迎亲车队"
        },
        {
          "src": "assets/photos/w017.jpg",
          "yaw": 225.0,
          "pitch": 0,
          "confidence": 0.9101,
          "by": "auto",
          "caption": "高架路口"
        },
        {
          "src": "assets/photos/w018.jpg",
          "yaw": 255.0,
          "pitch": 0,
          "confidence": 0.8805,
          "by": "auto",
          "caption": "婚车贴囍"
        },
        {
          "src": "assets/photos/w019.jpg",
          "yaw": 284.9,
          "pitch": 0,
          "confidence": 0.8077,
          "by": "auto",
          "caption": "抵达酒店"
        }
      ]
    },
    {
      "id": "yishi",
      "name": "礼堂",
      "sub": "酒店礼堂 · 拜堂",
      "chapter": "仪式",
      "time": "12:18",
      "panorama": "assets/panos/yishi.jpg",
      "map": {
        "x": 0.77,
        "y": 0.22
      },
      "geo": {
        "lng": 120.062,
        "lat": 30.247
      },
      "photos": [
        {
          "src": "assets/photos/w021.jpg",
          "yaw": 7,
          "pitch": -8,
          "confidence": 1.0,
          "by": "manual",
          "caption": "交换戒指"
        },
        {
          "src": "assets/photos/w022.jpg",
          "yaw": 74.8,
          "pitch": 0,
          "confidence": 0.8255,
          "by": "auto",
          "caption": "红毯入场"
        },
        {
          "src": "assets/photos/w023.jpg",
          "yaw": 134.9,
          "pitch": 0,
          "confidence": 0.8756,
          "by": "auto",
          "caption": "证婚致辞"
        },
        {
          "src": "assets/photos/w024.jpg",
          "yaw": 74.9,
          "pitch": 0,
          "confidence": 0.8669,
          "by": "auto",
          "caption": "抛捧花"
        },
        {
          "src": "assets/photos/w025.jpg",
          "yaw": 194.9,
          "pitch": 0,
          "confidence": 0.9209,
          "by": "auto",
          "caption": "拜堂礼"
        },
        {
          "src": "assets/photos/w026.jpg",
          "yaw": 224.9,
          "pitch": 0,
          "confidence": 0.9278,
          "by": "auto",
          "caption": "香槟塔"
        },
        {
          "src": "assets/photos/w027.jpg",
          "yaw": 74.8,
          "pitch": 0,
          "confidence": 0.8523,
          "by": "auto",
          "caption": "双方父母登台"
        },
        {
          "src": "assets/photos/w028.jpg",
          "yaw": 254.9,
          "pitch": 0,
          "confidence": 0.8921,
          "by": "auto",
          "caption": "交杯酒"
        },
        {
          "src": "assets/photos/w029.jpg",
          "yaw": 255.0,
          "pitch": 0,
          "confidence": 0.9303,
          "by": "auto",
          "caption": "掌声雷动"
        },
        {
          "src": "assets/photos/w030.jpg",
          "yaw": 45.3,
          "pitch": 0,
          "confidence": 0.8582,
          "by": "auto",
          "caption": "全场合影"
        }
      ]
    },
    {
      "id": "yanxi",
      "name": "宴席厅",
      "sub": "酒店宴席厅 · 敬酒",
      "chapter": "宴席",
      "time": "18:00",
      "panorama": "assets/panos/yanxi.jpg",
      "map": {
        "x": 0.9,
        "y": 0.32
      },
      "geo": {
        "lng": 120.0628,
        "lat": 30.2463
      },
      "photos": [
        {
          "src": "assets/photos/w031.jpg",
          "yaw": 7,
          "pitch": -10,
          "confidence": 1.0,
          "by": "manual",
          "caption": "第一支舞"
        },
        {
          "src": "assets/photos/w032.jpg",
          "yaw": 45.1,
          "pitch": 0,
          "confidence": 0.8988,
          "by": "auto",
          "caption": "挨桌敬酒"
        },
        {
          "src": "assets/photos/w033.jpg",
          "yaw": 104.8,
          "pitch": 0,
          "confidence": 0.8609,
          "by": "auto",
          "caption": "切蛋糕"
        },
        {
          "src": "assets/photos/w034.jpg",
          "yaw": 135.1,
          "pitch": 0,
          "confidence": 0.912,
          "by": "auto",
          "caption": "宾客碰杯"
        },
        {
          "src": "assets/photos/w035.jpg",
          "yaw": 45.0,
          "pitch": 0,
          "confidence": 0.8946,
          "by": "auto",
          "caption": "父亲致辞"
        },
        {
          "src": "assets/photos/w036.jpg",
          "yaw": 195.0,
          "pitch": 0,
          "confidence": 0.923,
          "by": "auto",
          "caption": "灯光秀"
        },
        {
          "src": "assets/photos/w037.jpg",
          "yaw": 45.0,
          "pitch": 0,
          "confidence": 0.8978,
          "by": "auto",
          "caption": "抽奖环节"
        },
        {
          "src": "assets/photos/w038.jpg",
          "yaw": 255.0,
          "pitch": 0,
          "confidence": 0.877,
          "by": "auto",
          "caption": "宾客合影"
        },
        {
          "src": "assets/photos/w039.jpg",
          "yaw": 284.9,
          "pitch": 0,
          "confidence": 0.861,
          "by": "auto",
          "caption": "婚宴留影墙"
        },
        {
          "src": "assets/photos/w040.jpg",
          "yaw": 344.8,
          "pitch": 0,
          "confidence": 0.8275,
          "by": "auto",
          "caption": "送客致谢"
        }
      ]
    }
  ],
  "links": [
    {
      "from": "jieqin",
      "to": "chufa",
      "yaw": 200
    },
    {
      "from": "chufa",
      "to": "yishi",
      "yaw": 100
    },
    {
      "from": "yishi",
      "to": "yanxi",
      "yaw": 300
    },
    {
      "from": "chufa",
      "to": "jieqin",
      "yaw": 20
    },
    {
      "from": "yishi",
      "to": "chufa",
      "yaw": 280
    },
    {
      "from": "yanxi",
      "to": "yishi",
      "yaw": 120
    }
  ]
};
