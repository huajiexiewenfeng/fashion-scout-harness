# 当前会话浏览器来源

只适用于已配置项目及明确已接受的单站 browser Run。固定站点如下；不能以任意站点或 CDN 替换。来源观察不是登录、CAPTCHA 或安全限制绕过。正常页面不可用、警告、结构与身份异常或限额触顶时停止并保留 partial；不自行更换入口／代理／DNS／保护设置，不访问被客户端阻断的 products.json/.js，不新增依赖或定时器。

| site_id | 正常列表入口 | 冻结 browser adapter |
|---|---|---|
| futario | https://futario.com/collections/new-in | futario-browser-host-v1 |
| rihoas | https://www.rihoas.com/collections/new-in-dresses | rihoas-browser-host-v1 |
| simpleretro | https://www.simpleretro.com/collections/newest-products | simpleretro-browser-host-v1 |

用户要求三站巡检时，Codex依次执行三个单站 Run，通常 Futario → RIHOAS → SimpleRetro。一次开始意图包含这三个顺序采集步骤；用户不用填写 JSON。每站的新 start 显式 site_ids:[该站]；先处理已有活动 Run 的原意图与续采，再开始下一站。服务拒绝把另一个站点复用到活动 Run；不取消、重写旧 Run 或清空库。每站现行程序默认为 240 张选中资产、100 条观察、前台 3600 秒、idle 600 秒，适合约 20 款的有限可见图库巡检，不能保证全站。已保存自定义限额继续生效，可按当前授权临时覆盖。仍受 64 MiB 接收默认上限、单图 25 MiB/5000万像素、存储与磁盘限制；以实际 attach 回执及累计计数为准。历史 Run 保留原限额，旧 12 张 smoke 限额不是新巡检永久规则。

1. 先读 latest/progress/default-plan/intents/sites。新巡检只在明确开始意图下固定 start，例如 `{"new_intent":true,"overrides":{"source_mode":"browser","site_ids":["rihoas"]}}`，将已授权临时日期和限额一并冻结；无需修改默认方案。回执确认真实 run.id、snapshot.source_mode、site_ids、site_entries 与 adapter_versions。活动 HTTP Run 返回 SOURCE_MODE_CONFLICT，另一站活动 browser Run 返回 SITE_SCOPE_CONFLICT，不能 attach 或换键转换。
2. 对已接受 Run，固定 browser-attach，输入 new_intent:true/run_id。保存真实 session_id、epoch、limits。若等待 SOURCE_HOST_REQUIRED，先固定 browser-continue 同 run_id，随后 attach；这只是继续已接受的来源采集，不能生成新 Run。每个固定写操作会建立自身意图记录，new_intent:true 不表示每张图都需用户另行确认。
3. 用本会话支持的 `mcp__cua_repl`。首次调用严格只执行一个文档允许的 entry API；优先当前来源 tab，或创建已授权 URL 的可见 tab。读取返回文档和实际快照后才继续。仅使用文档允许的 DOM 只读 evaluate/locator 与 `tab.capabilities.get('pageAssets')`。Python 不调用 Codex 内部协议，不读浏览器 profile、Cookie 或隐藏缓存。导航次数另记，浏览器自动资源计数／字节／peer 一律 unknown。
4. 在正常 listing 上检查实际 DOM 产品身份字段，保留 source_id 数字串及 URL/handle/title。不能从 slug、图片名或列表顺序编造数字 ID。按真实 pass/page/terminal 提交 browser-observe listing；看到 Load More 或 Next 不等于终页。RIHOAS/SimpleRetro 第二页真实 page_url 必须保留 `?page=2`，仅同入口路径的 `page=1..1000` 查询被接受，page_number须一致；不冒填第一页、不带排序/追踪/重复参数。Futario Load More 的当前 URL 可以不变，page_number记录实际追加批次，新批次不重复此前卡片。完整列表只在两遍稳定 ID 集和各自结束证据具备时由 Worker 判定，不能传 discovery_complete/succeeded。有限小样本应如实不完整。
5. 读 browser-status，等 listing message applied 与 products.eligible。仅对 eligible 商品查看已许可正常 detail；读全体当前可观察图库链接／编号和闭合证据，不为快捷 smoke 只取缩略图。提交 detail 前把观察列表冻结，source_image_id 可用规范化观察 URL 摘要加序号，不能冒充 Shopify 图像 ID；ordinal 0 起。对没有可靠总数的图库 expected_count:null/gallery_end_observed:false。可见选项标签只放 observed_options，不能伪造变体 ID、日期或原始分辨率。
6. 固定 browser-status，等 detail message applied 且 Worker 已发 tickets。每个 ticket 必须匹配原 source_image_id/source_url/product_id。在 pageAssets 的新 inventory 中按这些确切 URL 找资产，调用该工具当前文档的 bundle({inventoryId,assetIds})。不沿用旧会话 tab/inventory/asset ID，不把先前诊断文件当已接受 Run 的实时素材。工具没有可靠网络硬上限；选中导出次数和实际文件大小另记。找不到资产时固定 browser-asset-failure，不能忽略缺图。
7. 保存 tool 返回的 directoryPath/manifestPath 和选中资产 id；以有限只读句柄核对实际文件 SHA、大小、URL（可用项目普通文件工具计算元数据，不读取私密数据）。受控 JSON 用结构化写文件方式生成。固定 browser-upload 使用 run_id/session_id/ticket_id/native_directory/manifest_path/asset_id/source_url/sha256/bytes/new_intent:true。本机客户端只读 native TEMP/browser-use/assets/UUID 下普通文件，不把文件路径发给服务，不给网页令牌。一个已收到回执只证明接收，需 browser-status 等 archived，Pillow/Archive 合格后才算入库。
8. 在已选文件收到或失败有记录后提交 finish 观察。它只是关闭来源提交，Worker 自己重算结果。完整原商品图集未知仍 partial，即使 browser.gallery 全齐；6 枚举/5 入库必须缺失 1。打开本机页面和收藏／导出继续用既有固定命令，不把来源图片呈现记为用户已看。

通信断开或工具回执丢失先 intents → resume 原 intent_id，不重 bundle、不换键。browser-upload 的 sending 恢复先查服务端原键接收回执；完整接收后 native 临时文件消失也能核对。尚未完成的旧会话上传在续采新 epoch 后被拒绝；重新读取同 Run ticket 后按授权剩余限额建立新上传操作，保留旧记录。等待前台不耗 R1 处理时钟，不重复领取或阻塞独立导出／维护。读／ensure／open 不会主动进行浏览器来源采集。

API 固定前缀 `/v1/runs/{id}/browser-source`：GET 状态／receipts，POST attach/observations/continue，POST assets/{ticket}/body 或 failure；由固定客户端路由，模型不能提供 method、base URL、header、request_key 或任意服务端文件路径。

## 2026-10-07 正常页面 DOM 依据

以下是已验证结构的定位依据，每次仍读取当前快照；模板数字不能硬编码，结构/身份异常就停止。只读 DOM，不点击购物、快捷购买或推荐商品。

- Futario：使用已有真实商品数字 ID。当前商品选项严格限于 `document.querySelector('h1').closest('.product-single__meta')` 下的 `fieldset.variant-input-wrap`，核对 name=Color/Size、data-index=option1/option2及当前商品字段 ID。全页 fieldset 会混入 You May Also Like 推荐颜色，不能当作当前商品选项。
- RIHOAS：主列表容器下 `product-block[data-product-id]`，链接 `a.product-link`，标题 `.product-block__title`。详情推荐列表也有 product-block，不能全页采集。正常卡片链接可为该入口下 `/products/{handle}`，详情 canonical 可为 `/products/{handle}`；二者由本站数字 ID+handle对齐，保留各自真实观察 URL。已验证示例 ID 9589644001493、handle black-puffed-sleeve-tie-chiffon-mini-dress。主详情 `form[data-product-id]`，当前图库 `.slider__item[data-media-id][role=group]`，aria-label提供序号/总数（样例1 of 4至4 of 4）。只取当前主图库，不取推荐与营销图片。
- SimpleRetro：主列表 `[id^="product-list-"][id$="__main"] > product-card`，不能使用全页 product-list（存在隐藏推荐）。card[handle]与 `a.product-title`给链接/标题；数字 ID来自当前卡片 `form[id^="product_form_"]` 或 `quick-buy-modal` ID 最后的 `---数字`，button aria-controls可交叉核对，不点击按钮。handle中的variant参数不是商品 ID。同标题不同数字 ID保留为不同商品，不能按标题去重。主详情当前 h1与 `product-gallery[form^="product-form-"]` 或 `#judgeme_product_reviews[data-product-id]`交叉确认数字 ID；早期 SEO 文本可能是无关旧商品，不能正则扫全页猜身份。样例 Annora High-Waist Flared Jeans，ID 10366580523194，handle annora-high-waist-flared-jeans-1。主图库 `product-gallery .product-gallery__media[data-media-type="image"][data-media-id]`，aria-label样例 Item 1 of 9至9 of 9。

图库允许路径：Futario本站 `/cdn/shop/files/`、`/cdn/shop/products/`及已验证 Shopify店铺前缀 `cdn.shopify.com/s/files/1/0600/7672/0193/`；RIHOAS/SimpleRetro仅各自精确 www host下 `/cdn/shop/files/`。源图查询保留真实 v/width等参数；ticket、manifest和上传 URL必须逐字一致。不得使用别站图库、其它 Shopify店铺、lantern.roeye.com、营销 CloudFront或任意共享 host。商品 ID在库内为 site_id-数字ID，不能将其它站观察、session、ticket带入当前 Run。

未知日期继续 unknown；没有可靠图库闭合证据继续 incomplete。新款默认列表只计有实际归档且可解码、摘要匹配的商品，metadata-only不显示空卡，仍可按商品 ID审计。已有收藏/排除/已看记录不重置；收藏视图保留缺图审计和已有导出语义。

本地合成验证和实际来源严格区分。每次采集范围/限额依据当前用户明确意图和有效任务约束冻结，读取当前Run累计计数；历史诊断次数、旧预算或倒计时不能成为永久产品规则或自动新访问许可。按当前限额执行，正常页面不可用、限制或触顶时如实停止；浏览器背景网络仍未知。用户不手工操作这些文件或输入。
