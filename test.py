import openai
client = openai.OpenAI(
  api_key="sk-99adxildjL4HKOHHBe133cA46d274892Bf9c6a9dEa69F3F4",  # 换成你在 AiHubMix 生成的密钥
  base_url="https://aihubmix.com/v1"
)


response = client.chat.completions.create(
  model="qwen3-vl-flash",
  messages=[
      {
          "role": "user",
          "content": [
              {
                  # 直接传入视频文件时，请将type的值设置为video_url
                  "type": "video_url",
                  "video_url": {"url": "https://help-static-aliyun-doc.aliyuncs.com/file-manage-files/zh-CN/20241115/cqqkru/1.mp4"}
              },
              {
                  "type": "image_url",
                  "image_url": {"url": "https://help-static-aliyun-doc.aliyuncs.com/file-manage-files/zh-CN/20241022/emyrja/dog_and_girl.jpeg"}
              },
              {
                  "type": "text",
                  "text": "这段视频和图片的内容是什么?"
              }
          ]
      }
  ]
)

print(response.choices[0].message.content)