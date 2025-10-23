/*
 * Copyright (c) Microsoft Corporation. All rights reserved. Licensed under the MIT license.
 * See LICENSE in the project root for license information.
 */

/* global document, Office, Word */

Office.onReady((info) => {
  if (info.host === Office.HostType.Word) {
    const sideloadMsg = document.getElementById("sideload-msg");
    const appBody = document.getElementById("app-body");
    if (sideloadMsg) sideloadMsg.style.display = "none";
    if (appBody) appBody.style.display = "flex";

    // 绑定事件（添加null检查）
    const sendButton = document.getElementById('sendButton');
    const chatButton = document.getElementById('chatButton');
    if (sendButton) {
      sendButton.onclick = sendToFastGPT;
      console.log('sendButton bound successfully');
    } else {
      console.error('sendButton not found');
    }
    if (chatButton) {
      chatButton.onclick = toggleChatIframe;
      console.log('chatButton bound successfully');
    } else {
      console.error('chatButton not found');
    }
  }
});

// 调用FastGPT API（支持流式输出）
async function callFastGPT(prompt) {
  try {
    const response = await fetch('https://chatpub.com.cn/api/v1/chat/completions', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': 'Bearer openapi-kiNGQLcOCQzScQKvmNfSXxh6Z1YfZA89lZiJJzBmvTogiUJ9WNCar2JLdv'
      },
      body: JSON.stringify({
        model: 'gpt-3.5-turbo',  // 假设；如无需，设为空或调整
        messages: [{ role: 'user', content: prompt }],
        stream: true  // 新增：启用流式输出
      })
    });

    if (!response.ok) throw new Error(`HTTP ${response.status}: ${response.statusText}`);

    // 处理流式响应
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let fullResponse = '';  // 累积完整响应（可选，用于日志）

    // 清空输出并显示加载
    const outputElement = document.getElementById('chatOutput');
    if (outputElement) {
      outputElement.innerText = '';  // 清空开始新响应
    }

    // 读取流
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      const chunk = decoder.decode(value);
      const lines = chunk.split('\n');
      for (const line of lines) {
        if (line.startsWith('data: ')) {
          const data = line.slice(6);
          if (data === '[DONE]') continue;  // 结束标志

          try {
            const parsed = JSON.parse(data);
            const delta = parsed.choices[0]?.delta?.content || '';
            if (delta) {
              fullResponse += delta;
              // 逐步追加到UI
              if (outputElement) {
                outputElement.innerText += delta;
                // 滚动到底部
                outputElement.scrollTop = outputElement.scrollHeight;
              }
            }
          } catch (parseError) {
            console.warn('Parse error in stream chunk:', parseError);
          }
        }
      }
    }

    console.log('Full streamed response:', fullResponse);  // 日志完整响应
    return fullResponse;  // 返回完整文本（备用）

  } catch (error) {
    console.error('FastGPT API Error:', error);
    const outputElement = document.getElementById('chatOutput');
    if (outputElement) {
      outputElement.innerText = `Error: ${error.message}. Check console.`;
    }
    return `Error: ${error.message}. Check console.`;
  }
}

// 发送输入到API，显示输出
async function sendToFastGPT() {
  const inputElement = document.getElementById('promptInput');
  const outputElement = document.getElementById('chatOutput');
  const sendButton = document.getElementById('sendButton');
  if (!inputElement || !outputElement || !sendButton) {
    console.error('Missing UI elements for sendToFastGPT');
    return;
  }

  const input = inputElement.value.trim();
  if (!input) {
    outputElement.innerText = 'Please enter a prompt.';
    return;
  }

  // 显示加载
  outputElement.innerText = 'Generating response...';
  sendButton.disabled = true;

  // 调用流式API（会逐步更新outputElement）
  await callFastGPT(input);

  // 响应结束，启用按钮
  sendButton.disabled = false;

  // 清空输入（可选）
  inputElement.value = '';
}

// 切换iframe显示
function toggleChatIframe() {
  const inputElement = document.getElementById('promptInput');
  const outputElement = document.getElementById('chatOutput');
  const iframe = document.getElementById('chatIframe');
  const button = document.getElementById('chatButton');
  if (!inputElement || !outputElement || !iframe || !button) return;

  if (iframe.style.display === 'none') {
    // 打开iframe：折叠输入/输出到最小（顶部5vh），iframe占剩余
    inputElement.style.height = '5vh';
    outputElement.style.height = '5vh';
    iframe.style.display = 'block';
    iframe.style.height = '80vh';
    button.innerText = '关闭AI对话';
  } else {
    // 关闭iframe：恢复输入/输出高度
    inputElement.style.height = '30vh';
    outputElement.style.height = '60vh';
    iframe.style.display = 'none';
    iframe.style.height = '400px';
    button.innerText = 'AI对话';
  }
}