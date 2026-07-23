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
    [120.0057, 30.2790],
    [120.0125, 30.2799],
    [120.0198, 30.2803],
    [120.0271, 30.2801],
    [120.0276, 30.2700],
    [120.0290, 30.2580],
    [120.0410, 30.2520],
    [120.0620, 30.2470]
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
      "geo": { "lng": 120.0057, "lat": 30.2790 },
      "photos": [
        {
          "src": "assets/photos/w001.jpg",
          "yaw": 15,
          "pitch": 0,
          "confidence": 1.0,
          "by": "manual",
          "caption": "堵门红包"
        },
        {
          "src": "assets/photos/w002.jpg",
          "yaw": 74.9,
          "pitch": 0,
          "confidence": 0.8757,
          "by": "auto",
          "caption": "伴娘团拦门"
        },
        {
          "src": "assets/photos/w003.jpg",
          "yaw": 164.6,
          "pitch": 0,
          "confidence": 0.8659,
          "by": "auto",
          "caption": "改口敬茶"
        },
        {
          "src": "assets/photos/w004.jpg",
          "yaw": 75.0,
          "pitch": 0,
          "confidence": 0.8579,
          "by": "auto",
          "caption": "新娘家全家福"
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
      "geo": { "lng": 120.0271, "lat": 30.2801 },
      "photos": [
        {
          "src": "assets/photos/w005.jpg",
          "yaw": 30,
          "pitch": 0,
          "confidence": 1.0,
          "by": "manual",
          "caption": "婚车头车"
        },
        {
          "src": "assets/photos/w006.jpg",
          "yaw": 194.9,
          "pitch": 0,
          "confidence": 0.9233,
          "by": "auto",
          "caption": "车队过城"
        },
        {
          "src": "assets/photos/w007.jpg",
          "yaw": 255.1,
          "pitch": 0,
          "confidence": 0.8487,
          "by": "auto",
          "caption": "后视镜别红花"
        },
        {
          "src": "assets/photos/w008.jpg",
          "yaw": 345.2,
          "pitch": 0,
          "confidence": 0.909,
          "by": "auto",
          "caption": "车队鸣笛"
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
      "geo": { "lng": 120.0620, "lat": 30.2470 },
      "photos": [
        {
          "src": "assets/photos/w009.jpg",
          "yaw": 10,
          "pitch": 5,
          "confidence": 1.0,
          "by": "manual",
          "caption": "交换戒指"
        },
        {
          "src": "assets/photos/w010.jpg",
          "yaw": 105.1,
          "pitch": 0,
          "confidence": 0.8984,
          "by": "auto",
          "caption": "拜堂"
        },
        {
          "src": "assets/photos/w011.jpg",
          "yaw": 74.8,
          "pitch": 0,
          "confidence": 0.8918,
          "by": "auto",
          "caption": "红毯步入礼堂"
        },
        {
          "src": "assets/photos/w012.jpg",
          "yaw": 284.9,
          "pitch": 0,
          "confidence": 0.8769,
          "by": "auto",
          "caption": "证婚人致辞"
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
      "geo": { "lng": 120.0628, "lat": 30.2463 },
      "photos": [
        {
          "src": "assets/photos/w013.jpg",
          "yaw": 25,
          "pitch": 0,
          "confidence": 1.0,
          "by": "manual",
          "caption": "第一支舞"
        },
        {
          "src": "assets/photos/w014.jpg",
          "yaw": 45.0,
          "pitch": 0,
          "confidence": 0.8988,
          "by": "auto",
          "caption": "挨桌敬酒"
        },
        {
          "src": "assets/photos/w015.jpg",
          "yaw": 224.9,
          "pitch": 0,
          "confidence": 0.8754,
          "by": "auto",
          "caption": "切蛋糕"
        },
        {
          "src": "assets/photos/w016.jpg",
          "yaw": 285.0,
          "pitch": 0,
          "confidence": 0.8359,
          "by": "auto",
          "caption": "宾客碰杯"
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
    }
  ]
};
