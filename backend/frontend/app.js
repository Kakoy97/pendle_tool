// API 基础路径（前后端合并后，使用相对路径）
const API_BASE = "/api";

// DOM 元素
const tabButtons = document.querySelectorAll(".tab-btn");
const tabContents = document.querySelectorAll(".tab-content");
const monitoredProjectsList = document.querySelector("#monitored-projects");
const unmonitoredProjectsList = document.querySelector("#unmonitored-projects");
const syncButton = document.querySelector("#sync-projects");
const stopAutoUpdateButton = document.querySelector("#stop-auto-update-btn");
const priceTestResults = document.querySelector("#price-test-results");
const priceTestStatus = document.querySelector("#price-test-status");
const createGroupButton = document.querySelector("#create-group-btn");
const newGroupNameInput = document.querySelector("#new-group-name");
const clearProjectsButton = document.querySelector("#clear-projects-btn");
const editModeButton = document.querySelector("#edit-mode-btn");
const saveChangesButton = document.querySelector("#save-changes-btn");
const monitoredSearchInput = document.querySelector("#monitored-search");
const unmonitoredSearchInput = document.querySelector("#unmonitored-search");
const reloadHistoryButton = document.querySelector("#reload-history-btn");
const historyList = document.querySelector("#history-list");
const addSmartMoneyButton = document.querySelector("#add-smart-money-btn");
const reloadSmartMoneyButton = document.querySelector("#reload-smart-money-btn");
const smartMoneyList = document.querySelector("#smart-money-list");

// 存储所有分组名称
let allGroups = ["其他"];

// 存储链信息映射 { chainId: { name, token_address } }
let chainMap = {};

// 编辑模式状态
let isEditMode = false;

// 搜索关键词
let searchKeywords = {
  monitored: "",
  unmonitored: "",
};

// 存储分组的展开状态（避免重新渲染时折叠）
let expandedGroups = new Set();

// 存储待保存的修改（在编辑模式下收集，点击保存时批量提交）
let pendingChanges = {
  groupChanges: {},  // { address: newGroup }
  monitorChanges: {}, // { address: isMonitored }
};

// 标签页切换
tabButtons.forEach((btn) => {
  btn.addEventListener("click", () => {
    const targetTab = btn.dataset.tab;
    
    // 更新按钮状态
    tabButtons.forEach((b) => b.classList.remove("active"));
    btn.classList.add("active");
    
    // 更新内容显示
    tabContents.forEach((content) => {
      content.classList.remove("active");
      if (content.id === `${targetTab}-tab`) {
        content.classList.add("active");
      }
    });
    
      // 如果切换到价格测试标签页，自动开启自动检测
      if (targetTab === "price-test") {
        // 自动开启自动检测功能
        if (!autoUpdateRunning) {
          startAutoUpdate();
        }
      }
      // 如果切换到历史记录标签页，加载历史记录
      if (targetTab === "history") {
        fetchHistory();
      }
      // 如果切换到聪明钱标签页，加载聪明钱列表
      if (targetTab === "smart-money") {
        fetchSmartMoney();
      }
    });
  });

// 加载项目列表
async function fetchProjects(sync = false) {
  monitoredProjectsList.innerHTML = "<p class='loading'>加载中...</p>";
  unmonitoredProjectsList.innerHTML = "<p class='loading'>加载中...</p>";
  
  try {
    console.log(`开始获取项目列表，sync=${sync}`);
    
    // 添加超时处理（45秒）
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), 45000);
    
    const response = await fetch(`${API_BASE}/pendle/projects?sync=${sync}`, {
      signal: controller.signal,
    });
    
    clearTimeout(timeoutId);
    
    if (!response.ok) {
      const errorText = await response.text();
      console.error(`API 错误: ${response.status}`, errorText);
      throw new Error(`API error: ${response.status} - ${errorText.substring(0, 100)}`);
    }
    
    const data = await response.json();
    console.log(`获取到项目列表: 监控=${data.monitored?.length || 0}, 未监控=${data.unmonitored?.length || 0}`);
    
    // 调试：检查第一个项目的数据结构
    if (data.monitored && data.monitored.length > 0) {
      const firstProject = data.monitored[0];
      console.log("第一个项目数据结构:", {
        name: firstProject.name,
        chain_id: firstProject.chain_id,
        tvl: firstProject.tvl,
        trading_volume_24h: firstProject.trading_volume_24h,
        implied_apy: firstProject.implied_apy,
        has_chain_in_map: firstProject.chain_id ? (chainMap[firstProject.chain_id] ? true : false) : false,
        chain_map_keys: Object.keys(chainMap),
      });
    }
    
    // 合并所有项目，让 renderProjects 根据修改后的状态决定显示位置
    const allProjects = [...(data.monitored || []), ...(data.unmonitored || [])];
    
    // 渲染时，renderProjects 会根据 isMonitored 参数和 pendingChanges 来过滤
    renderProjects(allProjects, monitoredProjectsList, true);
    renderProjects(allProjects, unmonitoredProjectsList, false);
  } catch (error) {
    console.error("获取项目列表失败:", error);
    if (error.name === 'AbortError') {
      monitoredProjectsList.innerHTML = `<p class="error">请求超时（45秒），请检查网络连接或后端服务</p>`;
      unmonitoredProjectsList.innerHTML = `<p class="error">请求超时（45秒），请检查网络连接或后端服务</p>`;
    } else {
      monitoredProjectsList.innerHTML = `<p class="error">无法获取项目列表: ${error.message}</p>`;
      unmonitoredProjectsList.innerHTML = `<p class="error">无法获取项目列表: ${error.message}</p>`;
    }
  }
}

// 渲染项目列表（列表式显示，按分组）
function renderProjects(projects, container, isMonitored) {
  if (!projects.length) {
    container.innerHTML = `<p class="empty-state">${isMonitored ? "暂无正在监控的项目" : "暂无未监控的项目"}</p>`;
    return;
  }
  
  // 应用待保存的修改到项目数据上（仅在编辑模式下）
  const projectsWithChanges = projects.map(project => {
    if (!isEditMode) {
      return project;
    }
    
    // 创建项目副本，应用待保存的修改
    const modifiedProject = { ...project };
    
    // 应用分组修改
    if (pendingChanges.groupChanges[project.address]) {
      modifiedProject.project_group = pendingChanges.groupChanges[project.address];
    }
    
    // 应用监控状态修改
    if (pendingChanges.monitorChanges.hasOwnProperty(project.address)) {
      modifiedProject.is_monitored = pendingChanges.monitorChanges[project.address];
    }
    
    return modifiedProject;
  });
  
  // 根据修改后的监控状态过滤项目
  const filteredProjects = projectsWithChanges.filter(p => p.is_monitored === isMonitored);
  
  if (!filteredProjects.length) {
    container.innerHTML = `<p class="empty-state">${isMonitored ? "暂无正在监控的项目" : "暂无未监控的项目"}</p>`;
    return;
  }
  
  // 获取搜索关键词
  const searchKeyword = isMonitored ? searchKeywords.monitored : searchKeywords.unmonitored;
  
  // 按项目分组归类（所有项目默认在"其他"组）
  let grouped = {};
  
  for (const project of filteredProjects) {
    // 强制所有项目都在"其他"组（除非用户手动修改过）
    const group = project.project_group || "其他";
    // 如果项目有分组但不是"其他"，也显示（用户手动设置的）
    // 但初始同步时，所有项目都应该在"其他"组
    if (!grouped[group]) {
      grouped[group] = [];
    }
    grouped[group].push(project);
  }
  
  // 如果有搜索关键词，过滤分组和项目
  if (searchKeyword && searchKeyword.trim()) {
    const keyword = searchKeyword.trim().toLowerCase();
    const filteredGrouped = {};
    
    for (const [groupName, groupProjects] of Object.entries(grouped)) {
      // 检查分组名称是否匹配
      const groupMatches = groupName.toLowerCase().includes(keyword);
      
      // 过滤项目：检查项目名称、地址、描述是否匹配
      const matchingProjects = groupProjects.filter(project => {
        const nameMatch = (project.name || "").toLowerCase().includes(keyword);
        const symbolMatch = (project.symbol || "").toLowerCase().includes(keyword);
        const addressMatch = (project.address || "").toLowerCase().includes(keyword);
        const descMatch = (project.description || "").toLowerCase().includes(keyword);
        return nameMatch || symbolMatch || addressMatch || descMatch;
      });
      
      // 如果分组名称匹配，或者有匹配的项目，则显示该分组
      if (groupMatches || matchingProjects.length > 0) {
        filteredGrouped[groupName] = groupMatches ? groupProjects : matchingProjects;
      }
    }
    
    grouped = filteredGrouped;
  }
  
  // 生成 HTML（列表式）
  let html = "";
  
  // 显示所有有项目的分组（包括用户手动创建的分组）
  // 如果分组不在 allGroups 中，也添加到 allGroups（确保下拉框中有这个选项）
  const groupNames = Object.keys(grouped);
  
  // 将新发现的分组添加到 allGroups（如果还没有）
  for (const groupName of groupNames) {
    if (!allGroups.includes(groupName)) {
      allGroups.push(groupName);
      console.log(`发现新分组 "${groupName}"，已添加到分组列表`);
    }
  }
  
  // 按分组名称排序，"其他"组放在最后
  groupNames.sort((a, b) => {
    if (a === "其他") return 1;
    if (b === "其他") return -1;
    return a.localeCompare(b);
  });
  
  // 更新 allGroups 排序
  allGroups.sort((a, b) => {
    if (a === "其他") return 1;
    if (b === "其他") return -1;
    return a.localeCompare(b);
  });
  
  for (const groupName of groupNames) {
    const groupProjects = grouped[groupName];
    const groupId = `group-${groupName.replace(/\s+/g, "-").toLowerCase()}-${isMonitored ? "monitored" : "unmonitored"}`;
    
    // 计算分组汇总
    const groupSummary = calculateGroupSummary(groupProjects);
    
    html += `
      <div class="project-group-row">
        <div class="project-group-header-row" onclick="toggleGroup('${groupId}')">
          <span class="project-group-name-row">${escapeHtml(groupName)}</span>
          <span class="project-group-count-row">${groupProjects.length} 个市场</span>
          <span class="project-group-summary-row">
            <span class="summary-item"><strong>TVL:</strong> $${formatNumber(groupSummary.tvl)}</span>
            <span class="summary-item"><strong>24hVOL:</strong> $${formatNumber(groupSummary.volume24h)}</span>
            <span class="summary-item"><strong>FixedAPY:</strong> ${formatPercent(groupSummary.apy)}</span>
          </span>
          <span class="project-group-toggle-row" id="${groupId}-toggle">${expandedGroups.has(groupId) ? '▲' : '▼'}</span>
        </div>
        <div class="project-group-content-row" id="${groupId}" style="display: ${expandedGroups.has(groupId) ? 'block' : 'none'};">
          ${groupProjects
            .map(
              (project) => `
                <div class="project-row">
                  <div class="project-row-main">
                    <div class="project-row-info">
                      <div class="project-row-name-section">
                        <a href="https://app.pendle.finance/trade/markets/${escapeHtml(project.address)}/swap?view=yt${project.chain_id && chainMap[project.chain_id] ? `&chain=${escapeHtml(chainMap[project.chain_id].name)}` : ""}" target="_blank" class="project-row-name-link">${escapeHtml(project.name || project.symbol || "未知项目")}</a>
                        ${project.chain_id ? (chainMap[project.chain_id] ? `<span class="project-row-chain">[${escapeHtml(chainMap[project.chain_id].name)}]</span>` : `<span class="project-row-chain">[链ID: ${project.chain_id}]</span>`) : ""}
                      </div>
                      <span class="project-row-address">${escapeHtml(project.address)}</span>
                      ${project.expiry ? `<span class="project-row-expiry">到期: ${formatDateOnly(project.expiry)}</span>` : ""}
                    </div>
                    <div class="project-row-metrics">
                      <span class="metric-item"><strong>TVL:</strong> $${formatNumber(project.tvl)}</span>
                      <span class="metric-item"><strong>24hVOL:</strong> $${formatNumber(project.trading_volume_24h)}</span>
                      <span class="metric-item"><strong>FixedAPY:</strong> ${formatPercent(project.implied_apy)}</span>
                    </div>
                    <div class="project-row-actions">
                      <select class="project-group-select" 
                              onchange="changeProjectGroupInEditMode('${project.address}', this.value)" 
                              data-current-group="${escapeHtml(project.project_group || "其他")}"
                              data-original-group="${escapeHtml(project.project_group || "其他")}"
                              style="display: ${isEditMode ? 'block' : 'none'};">
                      </select>
                      ${
                        isEditMode
                          ? (isMonitored
                              ? `<button class="btn-danger btn-small" onclick="toggleMonitorInEditMode('${project.address}', false)">移除监控</button>`
                              : `<button class="btn-success btn-small" onclick="toggleMonitorInEditMode('${project.address}', true)">添加监控</button>`)
                          : ''
                      }
                    </div>
                  </div>
                </div>
              `
            )
            .join("")}
        </div>
      </div>
    `;
  }
  
  container.innerHTML = html;
  
  // 填充分组选择框的选项
  fillGroupSelects();
  
  // 根据编辑模式状态显示/隐藏编辑控件
  updateEditModeVisibility();
  
  // 恢复分组的展开状态（避免重新渲染时折叠）
  expandedGroups.forEach(groupId => {
    const content = document.getElementById(groupId);
    const toggle = document.getElementById(`${groupId}-toggle`);
    if (content && toggle) {
      content.style.display = "block";
      toggle.textContent = "▲";
    }
  });
}

// 更新编辑模式下的控件可见性
function updateEditModeVisibility() {
  const selects = document.querySelectorAll(".project-group-select");
  const monitorButtons = document.querySelectorAll(".project-row-actions button");
  
  selects.forEach(select => {
    select.style.display = isEditMode ? "block" : "none";
  });
  
  // 注意：监控按钮的显示已经在 renderProjects 中根据 isEditMode 控制了
  // 这里只需要确保状态一致
}

// 加载所有分组
async function loadGroups() {
  try {
    console.log("开始加载分组列表");
    
    // 添加超时处理（10秒）
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), 10000);
    
    const response = await fetch(`${API_BASE}/pendle/projects/groups`, {
      signal: controller.signal,
    });
    
    clearTimeout(timeoutId);
    
    if (response.ok) {
      const data = await response.json();
      console.log(`获取到 ${data.groups?.length || 0} 个分组:`, data.groups?.map(g => g.name));
      
      // 获取所有分组名称（包括空分组）
      const groups = data.groups.map(g => g.name);
      
      // 确保"其他"组存在
      if (!groups.includes("其他")) {
        groups.push("其他");
        console.log("添加默认分组'其他'");
      }
      
      // 更新本地分组列表
      allGroups = groups.sort((a, b) => {
        if (a === "其他") return 1;
        if (b === "其他") return -1;
        return a.localeCompare(b);
      });
      
      console.log(`分组列表已更新:`, allGroups);
      fillGroupSelects();
    } else {
      const errorText = await response.text();
      console.error(`加载分组失败: ${response.status}`, errorText);
    }
  } catch (error) {
    console.error("加载分组失败:", error);
    if (error.name === 'AbortError') {
      console.error("加载分组超时（10秒）");
    } else {
      console.error("加载分组失败，错误详情:", error);
    }
    // 确保至少有"其他"组
    if (!allGroups.includes("其他")) {
      allGroups = ["其他"];
      console.log("使用默认分组'其他'");
    }
    // 即使加载失败，也尝试填充分组选择框（使用现有的分组列表）
    fillGroupSelects();
  }
}

// 填充所有分组选择框
function fillGroupSelects() {
  const selects = document.querySelectorAll(".project-group-select");
  console.log(`填充 ${selects.length} 个分组选择框，当前分组列表:`, allGroups);
  
  selects.forEach(select => {
    const currentGroup = select.dataset.currentGroup || "其他";
    // 清空并重新填充选项（不包含"选择分组..."选项）
    select.innerHTML = '';
    allGroups.forEach(group => {
      const option = document.createElement("option");
      option.value = group;
      option.textContent = group;
      if (group === currentGroup) {
        option.selected = true;
      }
      select.appendChild(option);
    });
  });
  
  console.log(`分组选择框已填充完成`);
}

// 切换分组展开/折叠
function toggleGroup(groupId) {
  const content = document.getElementById(groupId);
  const toggle = document.getElementById(`${groupId}-toggle`);
  
  if (content.style.display === "none") {
    content.style.display = "block";
    toggle.textContent = "▲";
    expandedGroups.add(groupId);
  } else {
    content.style.display = "none";
    toggle.textContent = "▼";
    expandedGroups.delete(groupId);
  }
}

// 创建新分组
async function createGroup() {
  const groupName = newGroupNameInput.value.trim();
  if (!groupName) {
    alert("请输入分组名称");
    return;
  }
  
  // 先检查本地列表（快速检查）
  if (allGroups.includes(groupName)) {
    alert("分组已存在（本地）");
    // 即使本地存在，也重新加载一次，确保同步
    await loadGroups();
    return;
  }
  
  try {
    console.log(`尝试创建分组: ${groupName}`);
    
    // 调用后端API创建分组
    const response = await fetch(`${API_BASE}/pendle/projects/groups?group_name=${encodeURIComponent(groupName)}`, {
      method: "POST",
    });
    
    if (!response.ok) {
      const error = await response.json();
      const errorMessage = error.detail || "创建分组失败";
      
      // 如果分组已存在，重新加载分组列表
      if (response.status === 400 && errorMessage.includes("已存在")) {
        console.log(`分组 "${groupName}" 已存在于数据库，重新加载分组列表`);
        await loadGroups();  // 重新加载，确保分组在下拉框中显示
        alert(`分组 "${groupName}" 已存在，已添加到选择列表中`);
        newGroupNameInput.value = "";
        return;
      }
      
      throw new Error(errorMessage);
    }
    
    const data = await response.json();
    console.log(`分组创建成功:`, data);
    
    // 重新加载分组列表（从数据库获取最新数据）
    await loadGroups();
    
    newGroupNameInput.value = "";
    alert(`分组 "${groupName}" 已创建，现在可以将项目移动到此分组`);
  } catch (error) {
    console.error("创建分组失败:", error);
    alert(`创建分组失败: ${error.message}`);
  }
}

// 修改项目分组（旧版本，保留用于非编辑模式，但现在应该使用编辑模式）
async function changeProjectGroup(address, newGroup) {
  // 如果在编辑模式下，使用编辑模式的函数
  if (isEditMode) {
    changeProjectGroupInEditMode(address, newGroup);
    return;
  }
  
  if (!newGroup) {
    return; // 用户取消了选择
  }
  
  try {
    console.log(`修改项目 ${address} 的分组为: ${newGroup}`);
    
    const response = await fetch(`${API_BASE}/pendle/projects/${address}/group?group_name=${encodeURIComponent(newGroup)}`, {
      method: "PATCH",
    });
    
    if (!response.ok) {
      const error = await response.json();
      throw new Error(error.detail || "修改分组失败");
    }
    
    console.log(`项目分组修改成功`);
    
    // 如果新分组不在列表中，添加到列表
    if (!allGroups.includes(newGroup)) {
      allGroups.push(newGroup);
      allGroups.sort((a, b) => {
        if (a === "其他") return 1;
        if (b === "其他") return -1;
        return a.localeCompare(b);
      });
      console.log(`新分组 "${newGroup}" 已添加到本地列表`);
    }
    
    // 重新加载项目列表和分组列表（确保从数据库获取最新数据）
    // 注意：先加载分组，再加载项目，确保分组在下拉框中可用
    try {
      await loadGroups();  // 先加载分组，确保新分组在下拉框中可用
    } catch (error) {
      console.warn("加载分组失败，但继续加载项目列表:", error);
    }
    await fetchProjects(false);  // 再加载项目列表（这会自动显示所有有项目的分组）
    
    console.log(`项目列表和分组列表已刷新`);
    
  } catch (error) {
    console.error("修改分组失败:", error);
    alert(`修改分组失败: ${error.message}`);
  }
}

// 进入编辑模式
function enterEditMode() {
  isEditMode = true;
  editModeButton.style.display = "none";
  saveChangesButton.style.display = "block";
  
  // 重置待保存的修改
  pendingChanges = {
    groupChanges: {},
    monitorChanges: {},
  };
  
  // 重新渲染项目列表（显示编辑控件）
  fetchProjects(false);
  
  console.log("已进入编辑模式");
}

// 退出编辑模式（取消修改）
function exitEditMode() {
  isEditMode = false;
  editModeButton.style.display = "block";
  saveChangesButton.style.display = "none";
  
  // 重置待保存的修改
  pendingChanges = {
    groupChanges: {},
    monitorChanges: {},
  };
  
  // 重新渲染项目列表（隐藏编辑控件）
  fetchProjects(false);
  
  console.log("已退出编辑模式");
}

// 保存所有修改
async function saveAllChanges() {
  if (Object.keys(pendingChanges.groupChanges).length === 0 && 
      Object.keys(pendingChanges.monitorChanges).length === 0) {
    // 没有修改，静默返回，不显示提示
    return;
  }
  
  try {
    console.log("开始保存修改:", pendingChanges);
    
    // 批量保存分组修改
    const groupPromises = Object.entries(pendingChanges.groupChanges).map(
      ([address, newGroup]) =>
        fetch(`${API_BASE}/pendle/projects/${address}/group?group_name=${encodeURIComponent(newGroup)}`, {
          method: "PATCH",
        })
    );
    
    // 批量保存监控状态修改
    const monitorPromises = Object.entries(pendingChanges.monitorChanges).map(
      ([address, isMonitored]) =>
        fetch(`${API_BASE}/pendle/projects/${address}/monitor`, {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
          },
          body: JSON.stringify({
            address: address,
            is_monitored: isMonitored,
          }),
        })
    );
    
    // 等待所有请求完成
    const allPromises = [...groupPromises, ...monitorPromises];
    const results = await Promise.allSettled(allPromises);
    
    // 检查是否有失败的请求
    const failures = results.filter(r => r.status === 'rejected' || 
      (r.status === 'fulfilled' && !r.value.ok));
    
    if (failures.length > 0) {
      console.error("部分修改保存失败:", failures);
      alert(`保存完成，但有 ${failures.length} 个修改失败，请检查控制台`);
    } else {
      console.log("所有修改已成功保存");
      alert(`已成功保存 ${allPromises.length} 个修改`);
    }
    
    // 退出编辑模式并刷新列表
    exitEditMode();
    await fetchProjects(false);
    await loadGroups();
    
  } catch (error) {
    console.error("保存修改失败:", error);
    alert(`保存失败: ${error.message}`);
  }
}

// 在编辑模式下修改项目分组（不立即保存）
function changeProjectGroupInEditMode(address, newGroup) {
  if (!isEditMode) {
    return;
  }
  
  if (!newGroup) {
    // 用户取消了选择，恢复原始分组
    delete pendingChanges.groupChanges[address];
    // 恢复下拉框显示
    const select = document.querySelector(`select[onchange*="${address}"]`);
    if (select) {
      const originalGroup = select.dataset.originalGroup || "其他";
      select.value = originalGroup;
    }
    return;
  }
  
  // 记录修改
  pendingChanges.groupChanges[address] = newGroup;
  console.log(`记录分组修改: ${address} -> ${newGroup}`);
  
  // 立即更新UI（移动到新分组）
  updateProjectInUI(address, { group: newGroup });
}

// 在编辑模式下切换监控状态（不立即保存）
function toggleMonitorInEditMode(address, isMonitored) {
  if (!isEditMode) {
    return;
  }
  
  // 记录修改
  pendingChanges.monitorChanges[address] = isMonitored;
  console.log(`记录监控状态修改: ${address} -> ${isMonitored}`);
  
  // 立即更新UI（移动到对应列表）
  updateProjectInUI(address, { isMonitored: isMonitored });
}

// 更新项目在UI中的显示（立即生效，但不保存到数据库）
function updateProjectInUI(address, changes) {
  console.log(`UI更新: ${address}`, changes);
  
  // 立即重新渲染项目列表，应用待保存的修改
  // 这样项目会立即显示在正确的位置（监控/未监控列表，正确的分组）
  fetchProjects(false);
}

// 将函数暴露到全局
window.toggleGroup = toggleGroup;
window.changeProjectGroup = changeProjectGroup;
window.changeProjectGroupInEditMode = changeProjectGroupInEditMode;
window.toggleMonitorInEditMode = toggleMonitorInEditMode;

// 添加监控（旧版本，保留用于非编辑模式，但现在应该使用编辑模式）
async function addMonitor(address) {
  // 如果在编辑模式下，使用编辑模式的函数
  if (isEditMode) {
    toggleMonitorInEditMode(address, true);
    return;
  }
  
  try {
    const response = await fetch(`${API_BASE}/pendle/projects/${address}/monitor`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        address: address,
        is_monitored: true,
      }),
    });
    
    if (!response.ok) {
      const error = await response.json();
      throw new Error(error.detail || "添加监控失败");
    }
    
    // 重新加载项目列表
    await fetchProjects(false);
  } catch (error) {
    console.error(error);
    alert(`添加监控失败: ${error.message}`);
  }
}

// 移除监控（旧版本，保留用于非编辑模式，但现在应该使用编辑模式）
async function removeMonitor(address) {
  // 如果在编辑模式下，使用编辑模式的函数
  if (isEditMode) {
    toggleMonitorInEditMode(address, false);
    return;
  }
  
  if (!confirm("确定要移除监控吗？")) {
    return;
  }
  
  try {
    const response = await fetch(`${API_BASE}/pendle/projects/${address}/monitor`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        address: address,
        is_monitored: false,
      }),
    });
    
    if (!response.ok) {
      const error = await response.json();
      throw new Error(error.detail || "移除监控失败");
    }
    
    // 重新加载项目列表
    await fetchProjects(false);
  } catch (error) {
    console.error(error);
    alert(`移除监控失败: ${error.message}`);
  }
}

// 同步项目
async function syncProjects() {
  syncButton.disabled = true;
  syncButton.textContent = "同步中...";
  
  try {
    const response = await fetch(`${API_BASE}/pendle/projects/sync`, {
      method: "POST",
    });
    
    if (!response.ok) {
      const error = await response.json();
      throw new Error(error.detail || "同步失败");
    }
    
    const data = await response.json();
    alert(`同步成功！已同步 ${data.count} 个项目`);
    
    // 重新加载项目列表
    await fetchProjects(false);
    // 重新加载同步时间
    await loadLastSyncTime();
  } catch (error) {
    console.error(error);
    alert(`同步失败: ${error.message}`);
  } finally {
    syncButton.disabled = false;
    syncButton.textContent = "同步项目";
  }
}


// 将 UTC 时间转换为北京时间（UTC+8）
function toBeijingTime(utcDate) {
  if (!utcDate) return null;
  const date = new Date(utcDate);
  // 如果输入是字符串，需要确保正确解析
  if (typeof utcDate === "string" && !utcDate.includes("Z") && !utcDate.includes("+")) {
    // 假设是 UTC 时间，添加 Z 标记
    return new Date(utcDate + "Z");
  }
  return date;
}

// 格式化日期为北京时间
function formatDate(input) {
  if (!input) return "";
  const beijingDate = toBeijingTime(input);
  // 使用中文格式显示，指定时区为 Asia/Shanghai
  return beijingDate.toLocaleString("zh-CN", { 
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
    timeZone: "Asia/Shanghai"
  });
}

// 格式化日期（只显示日期部分，北京时间）
function formatDateOnly(input) {
  if (!input) return "";
  const beijingDate = toBeijingTime(input);
  return beijingDate.toLocaleDateString("zh-CN", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    timeZone: "Asia/Shanghai"
  });
}

function escapeHtml(str) {
  if (!str) return "";
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

// 将函数暴露到全局，供 onclick 使用
window.addMonitor = addMonitor;
window.removeMonitor = removeMonitor;

// 清空项目数据
async function clearProjects() {
  if (!confirm("确定要清空所有项目数据吗？此操作不可恢复！")) {
    return;
  }
  
  try {
    const response = await fetch(`${API_BASE}/pendle/projects/clear`, {
      method: "POST",
    });
    
    if (!response.ok) {
      const error = await response.json();
      throw new Error(error.detail || "清空失败");
    }
    
    const data = await response.json();
    alert(`已清空 ${data.deleted_count} 个项目`);
    
    // 重新加载项目列表
    await fetchProjects(false);
  } catch (error) {
    console.error(error);
    alert(`清空失败: ${error.message}`);
  }
}

// 搜索功能
function handleSearch(isMonitored, keyword) {
  if (isMonitored) {
    searchKeywords.monitored = keyword;
  } else {
    searchKeywords.unmonitored = keyword;
  }
  
  // 重新渲染项目列表（应用搜索过滤）
  fetchProjects(false);
}

// 存储项目结果，用于动态更新
const projectResultsMap = new Map();


// 更新价格测试结果显示（动态更新，不闪烁）
function updatePriceTestResultsDisplay() {
  if (!priceTestResults) return;
  
  const results = Array.from(projectResultsMap.values());
  if (results.length === 0) {
    priceTestResults.innerHTML = "<p class='loading'>正在测试价格...</p>";
    return;
  }
  
  // 获取最新的测试时间
  const latestResult = results.find(r => r.test_time) || results[0];
  const testTime = latestResult.test_time ? new Date(latestResult.test_time) : new Date();
  const timeStr = formatDate(testTime);
  
  let html = `<div class="price-test-header">
    <h3>测试时间: ${timeStr}</h3>
    <p>已测试项目数: ${results.length}</p>
  </div>`;
  
  html += '<div class="price-test-list">';
  
  for (const result of results) {
    if (result.success && result.aggregator_results) {
      // 有多个聚合器结果
      html += `
        <div class="price-test-item success" data-project-address="${escapeHtml(result.project_address)}">
          <div class="price-test-item-header">
            <span class="price-test-project-name">${escapeHtml(result.project_name || "未知项目")}</span>
            <span class="price-test-chain">[链ID: ${result.chain_id}]</span>
          </div>
          <div class="price-test-item-content">
      `;
      
      // 显示每个聚合器的结果（已按价值排序）
      for (const aggResult of result.aggregator_results) {
        if (aggResult.yt_amount !== undefined) {
          const ytAmountFormatted = formatYTAmount(aggResult.yt_amount, aggResult.yt_amount_raw);
          // 确保价值正确显示
          let valueDisplay = "";
          if (aggResult.yt_value_usd !== undefined && aggResult.yt_value_usd !== null) {
            const value = parseFloat(aggResult.yt_value_usd);
            if (!isNaN(value) && value > 0) {
              valueDisplay = ` (价值: $${value.toFixed(2)})`;
            }
          }
          // 调试信息
          if (!valueDisplay) {
            console.warn(`项目 ${result.project_name} 聚合器 ${aggResult.aggregator} 没有价值数据:`, {
              yt_amount: aggResult.yt_amount,
              yt_value_usd: aggResult.yt_value_usd,
              yt_price: result.yt_price
            });
          }
          html += `
            <div class="price-test-aggregator-result">
              <p class="price-test-result">
                <span class="price-test-aggregator-name">[${escapeHtml(aggResult.aggregator)}]</span>
                ${timeStr}  100 USDT  --> ${ytAmountFormatted} YT${valueDisplay}
              </p>
              ${aggResult.effective_apy ? `<p class="price-test-apy">有效 APY: ${(aggResult.effective_apy * 100).toFixed(2)}%</p>` : ""}
              ${aggResult.implied_apy ? `<p class="price-test-apy">隐含 APY: ${(aggResult.implied_apy * 100).toFixed(2)}%</p>` : ""}
              ${aggResult.price_impact !== undefined ? `<p class="price-test-apy">价格影响: ${(aggResult.price_impact * 100).toFixed(2)}%</p>` : ""}
            </div>
          `;
        } else if (aggResult.error) {
          html += `
            <div class="price-test-aggregator-result error">
              <p class="price-test-error">
                <span class="price-test-aggregator-name">[${escapeHtml(aggResult.aggregator)}]</span>
                测试失败: ${escapeHtml(aggResult.error)}
              </p>
            </div>
          `;
        }
      }
      
      html += `
          </div>
        </div>
      `;
    } else if (result.success) {
      // 兼容旧格式（单个结果）
      const ytAmount = parseFloat(result.yt_amount || 0);
      const ytAmountFormatted = formatYTAmount(result.yt_amount, result.yt_amount_raw);
      const valueDisplay = result.yt_value_usd ? ` (价值: $${parseFloat(result.yt_value_usd).toFixed(2)})` : "";
      html += `
        <div class="price-test-item success" data-project-address="${escapeHtml(result.project_address)}">
          <div class="price-test-item-header">
            <span class="price-test-project-name">${escapeHtml(result.project_name || "未知项目")}</span>
            <span class="price-test-chain">[链ID: ${result.chain_id}]</span>
          </div>
          <div class="price-test-item-content">
            <p class="price-test-result">${timeStr}  100 USDT  --> ${ytAmountFormatted} YT${valueDisplay}</p>
            ${result.effective_apy ? `<p class="price-test-apy">有效 APY: ${(result.effective_apy * 100).toFixed(2)}%</p>` : ""}
            ${result.implied_apy ? `<p class="price-test-apy">隐含 APY: ${(result.implied_apy * 100).toFixed(2)}%</p>` : ""}
          </div>
        </div>
      `;
    } else {
      html += `
        <div class="price-test-item error" data-project-address="${escapeHtml(result.project_address)}">
          <div class="price-test-item-header">
            <span class="price-test-project-name">${escapeHtml(result.project_name || "未知项目")}</span>
          </div>
          <div class="price-test-item-content">
            <p class="price-test-error">测试失败: ${escapeHtml(result.error || "未知错误")}</p>
          </div>
        </div>
      `;
    }
  }
  
  html += '</div>';
  
  // 使用 requestAnimationFrame 平滑更新，避免闪烁
  requestAnimationFrame(() => {
    priceTestResults.innerHTML = html;
  });
}

// 渲染价格测试结果
function renderPriceTestResults(results, testTime) {
  if (!results || results.length === 0) {
    priceTestResults.innerHTML = "<p class='empty-state'>没有测试结果</p>";
    return;
  }
  
  const testDate = new Date(testTime);
  const timeStr = formatDate(testDate);
  
  let html = `<div class="price-test-header">
    <h3>测试时间: ${timeStr}</h3>
    <p>测试项目数: ${results.length}</p>
  </div>`;
  
  html += '<div class="price-test-list">';
  
  for (const result of results) {
    if (result.success && result.aggregator_results) {
      // 有多个聚合器结果
      html += `
        <div class="price-test-item success">
          <div class="price-test-item-header">
            <span class="price-test-project-name">${escapeHtml(result.project_name || "未知项目")}</span>
            <span class="price-test-chain">[链ID: ${result.chain_id}]</span>
          </div>
          <div class="price-test-item-content">
      `;
      
      // 显示每个聚合器的结果（已按价值排序）
      for (const aggResult of result.aggregator_results) {
        if (aggResult.yt_amount !== undefined) {
          const ytAmountFormatted = formatYTAmount(aggResult.yt_amount, aggResult.yt_amount_raw);
          // 确保价值正确显示
          let valueDisplay = "";
          if (aggResult.yt_value_usd !== undefined && aggResult.yt_value_usd !== null) {
            const value = parseFloat(aggResult.yt_value_usd);
            if (!isNaN(value) && value > 0) {
              valueDisplay = ` (价值: $${value.toFixed(2)})`;
            }
          }
          // 调试信息
          if (!valueDisplay) {
            console.warn(`项目 ${result.project_name} 聚合器 ${aggResult.aggregator} 没有价值数据:`, {
              yt_amount: aggResult.yt_amount,
              yt_value_usd: aggResult.yt_value_usd,
              yt_price: result.yt_price
            });
          }
          html += `
            <div class="price-test-aggregator-result">
              <p class="price-test-result">
                <span class="price-test-aggregator-name">[${escapeHtml(aggResult.aggregator)}]</span>
                ${timeStr}  100 USDT  --> ${ytAmountFormatted} YT${valueDisplay}
              </p>
              ${aggResult.effective_apy ? `<p class="price-test-apy">有效 APY: ${(aggResult.effective_apy * 100).toFixed(2)}%</p>` : ""}
              ${aggResult.implied_apy ? `<p class="price-test-apy">隐含 APY: ${(aggResult.implied_apy * 100).toFixed(2)}%</p>` : ""}
              ${aggResult.price_impact !== undefined ? `<p class="price-test-apy">价格影响: ${(aggResult.price_impact * 100).toFixed(2)}%</p>` : ""}
            </div>
          `;
        } else if (aggResult.error) {
          html += `
            <div class="price-test-aggregator-result error">
              <p class="price-test-error">
                <span class="price-test-aggregator-name">[${escapeHtml(aggResult.aggregator)}]</span>
                测试失败: ${escapeHtml(aggResult.error)}
              </p>
            </div>
          `;
        }
      }
      
      html += `
          </div>
        </div>
      `;
    } else if (result.success) {
      // 兼容旧格式（单个结果）
      const ytAmount = parseFloat(result.yt_amount || 0);
      const ytAmountFormatted = formatYTAmount(result.yt_amount, result.yt_amount_raw);
      html += `
        <div class="price-test-item success">
          <div class="price-test-item-header">
            <span class="price-test-project-name">${escapeHtml(result.project_name || "未知项目")}</span>
            <span class="price-test-chain">[链ID: ${result.chain_id}]</span>
          </div>
          <div class="price-test-item-content">
            <p class="price-test-result">${timeStr}  100 USDT  --> ${ytAmountFormatted} YT</p>
            ${result.effective_apy ? `<p class="price-test-apy">有效 APY: ${(result.effective_apy * 100).toFixed(2)}%</p>` : ""}
            ${result.implied_apy ? `<p class="price-test-apy">隐含 APY: ${(result.implied_apy * 100).toFixed(2)}%</p>` : ""}
          </div>
        </div>
      `;
    } else {
      html += `
        <div class="price-test-item error">
          <div class="price-test-item-header">
            <span class="price-test-project-name">${escapeHtml(result.project_name || "未知项目")}</span>
          </div>
          <div class="price-test-item-content">
            <p class="price-test-error">测试失败: ${escapeHtml(result.error || "未知错误")}</p>
          </div>
        </div>
      `;
    }
  }
  
  html += '</div>';
  priceTestResults.innerHTML = html;
}

// 自动更新相关变量
let autoUpdateRunning = false;
let currentProjectIndex = 0;
let monitoredProjectsForUpdate = [];
let lastProjectListRefresh = 0;  // 上次刷新项目列表的时间戳
const PROJECT_LIST_REFRESH_INTERVAL = 300000;  // 每5分钟刷新一次项目列表（300000毫秒）

// 启动自动更新
async function startAutoUpdate() {
  if (autoUpdateRunning) {
    return;  // 已经在运行
  }
  
  // 检查必要的 DOM 元素是否存在
  if (!priceTestStatus) {
    console.error("priceTestStatus 元素不存在，无法启动自动更新");
    return;
  }
  
  // 获取监控的项目列表
  try {
    const response = await fetch(`${API_BASE}/pendle/projects?sync=false`);
    if (!response.ok) throw new Error("获取项目列表失败");
    const data = await response.json();
    monitoredProjectsForUpdate = [...(data.monitored || [])];
    
    if (monitoredProjectsForUpdate.length === 0) {
      if (priceTestStatus) {
        priceTestStatus.textContent = "没有监控的项目，无法启动自动更新";
      }
      return;
    }
    
    autoUpdateRunning = true;
    currentProjectIndex = 0;
    lastProjectListRefresh = Date.now();  // 记录启动时间
    if (stopAutoUpdateButton) {
      stopAutoUpdateButton.style.display = "inline-block";
    }
    if (priceTestStatus) {
      priceTestStatus.textContent = "自动更新已启动";
    }
    
    // 开始循环更新（递归方式，等待上一个请求完成后再等待3秒）
    updateNextProjectLoop();
    
  } catch (error) {
    console.error("启动自动更新失败:", error);
    if (priceTestStatus) {
      priceTestStatus.textContent = `启动自动更新失败: ${error.message}`;
    }
    autoUpdateRunning = false;
  }
}

// 停止自动更新
function stopAutoUpdate() {
  autoUpdateRunning = false;
  if (stopAutoUpdateButton) {
    stopAutoUpdateButton.style.display = "none";
  }
  if (priceTestStatus) {
    priceTestStatus.textContent = "自动更新已停止";
  }
}

// 刷新项目列表（用于自动更新时检测新增的项目）
async function refreshProjectListForUpdate() {
  try {
    const response = await fetch(`${API_BASE}/pendle/projects?sync=false`);
    if (!response.ok) throw new Error("获取项目列表失败");
    const data = await response.json();
    const newMonitoredProjects = [...(data.monitored || [])];
    
    // 获取新项目的地址集合
    const newAddresses = new Set(newMonitoredProjects.map(p => p.address));
    const currentAddresses = new Set(monitoredProjectsForUpdate.map(p => p.address));
    
    // 找出新增的项目
    const addedProjects = newMonitoredProjects.filter(p => !currentAddresses.has(p.address));
    
    // 找出被删除的项目（从当前列表中移除）
    monitoredProjectsForUpdate = monitoredProjectsForUpdate.filter(p => newAddresses.has(p.address));
    
    // 添加新增的项目到列表末尾
    if (addedProjects.length > 0) {
      monitoredProjectsForUpdate.push(...addedProjects);
      console.log(`检测到 ${addedProjects.length} 个新增项目，已添加到测试列表`);
    }
    
    // 如果当前索引超出范围，重置为0
    if (currentProjectIndex >= monitoredProjectsForUpdate.length && monitoredProjectsForUpdate.length > 0) {
      currentProjectIndex = 0;
    }
    
    lastProjectListRefresh = Date.now();
  } catch (error) {
    console.error("刷新项目列表失败:", error);
  }
}

// 循环更新下一个项目（递归方式）
async function updateNextProjectLoop() {
  if (!autoUpdateRunning) {
    return;  // 已停止
  }
  
  if (monitoredProjectsForUpdate.length === 0) {
    stopAutoUpdate();
    return;
  }
  
  // 如果距离上次刷新超过5分钟，刷新项目列表（检测新增项目）
  const now = Date.now();
  if (now - lastProjectListRefresh > PROJECT_LIST_REFRESH_INTERVAL) {
    await refreshProjectListForUpdate();
  }
  
  // 更新当前项目（等待请求完成）
  await updateSingleProjectPrice(monitoredProjectsForUpdate[currentProjectIndex]);
  
  // 如果已停止，不再继续
  if (!autoUpdateRunning) {
    return;
  }
  
  // 移动到下一个项目（循环）
  currentProjectIndex = (currentProjectIndex + 1) % monitoredProjectsForUpdate.length;
  
  // 等待3秒后更新下一个项目
  await new Promise(resolve => setTimeout(resolve, 3000));
  
  // 继续下一个
  if (autoUpdateRunning) {
    updateNextProjectLoop();
  }
}

// 更新单个项目的价格
async function updateSingleProjectPrice(project) {
  if (!project || !project.address) return;
  
  try {
    const response = await fetch(`${API_BASE}/pendle/projects/test-single-price?address=${encodeURIComponent(project.address)}`, {
      method: "POST",
    });
    
    if (!response.ok) {
      const error = await response.json();
      // 如果项目不存在，从列表中移除并继续下一个
      if (error.detail && error.detail.includes("项目不存在")) {
        console.warn(`项目 ${project.name || project.address} 已不存在，从测试列表中移除`);
        // 从列表中移除这个项目
        monitoredProjectsForUpdate = monitoredProjectsForUpdate.filter(p => p.address !== project.address);
        // 如果当前索引超出范围，重置为0
        if (currentProjectIndex >= monitoredProjectsForUpdate.length) {
          currentProjectIndex = 0;
        }
        // 如果列表为空，停止自动更新
        if (monitoredProjectsForUpdate.length === 0) {
          stopAutoUpdate();
          if (priceTestStatus) {
            priceTestStatus.textContent = "所有项目已不存在，自动更新已停止";
          }
        }
        return;
      }
      throw new Error(error.detail || "更新失败");
    }
    
    const data = await response.json();
    
    if (data.success) {
      // 更新或添加项目结果
      projectResultsMap.set(project.address, {
        ...data.result,
        test_time: data.test_time,
      });
      updatePriceTestResultsDisplay();
      if (priceTestStatus) {
        priceTestStatus.textContent = `正在更新: ${project.name || project.address} (${formatDate(data.test_time)})`;
      }
    } else if (data.message && data.message.includes("项目不存在")) {
      // 项目不存在，从列表中移除
      console.warn(`项目 ${project.name || project.address} 已不存在，从测试列表中移除`);
      monitoredProjectsForUpdate = monitoredProjectsForUpdate.filter(p => p.address !== project.address);
      if (currentProjectIndex >= monitoredProjectsForUpdate.length) {
        currentProjectIndex = 0;
      }
      if (monitoredProjectsForUpdate.length === 0) {
        stopAutoUpdate();
        if (priceTestStatus) {
          priceTestStatus.textContent = "所有项目已不存在，自动更新已停止";
        }
      }
    }
  } catch (error) {
    console.error(`更新项目 ${project.name} 价格失败:`, error);
  }
}

// 获取聚合器数量（从链信息中获取）
async function getAggregatorsCount(chainId) {
  try {
    const response = await fetch(`${API_BASE}/pendle/chain-ids`);
    if (!response.ok) return 4;  // 默认值
    const data = await response.json();
    const chain = data.chains?.find(c => c.id === chainId);
    if (chain && chain.aggregators) {
      const aggregators = typeof chain.aggregators === 'string' ? 
        JSON.parse(chain.aggregators) : chain.aggregators;
      return aggregators?.length || 4;
    }
    return 4;  // 默认值
  } catch (error) {
    console.error("获取聚合器数量失败:", error);
    return 4;  // 默认值
  }
}

// 事件监听
syncButton.addEventListener("click", syncProjects);
stopAutoUpdateButton?.addEventListener("click", stopAutoUpdate);
createGroupButton?.addEventListener("click", createGroup);
clearProjectsButton?.addEventListener("click", clearProjects);
editModeButton?.addEventListener("click", enterEditMode);
saveChangesButton?.addEventListener("click", saveAllChanges);
newGroupNameInput?.addEventListener("keypress", (e) => {
  if (e.key === "Enter") {
    createGroup();
  }
});

// 搜索框事件监听
monitoredSearchInput?.addEventListener("input", (e) => {
  handleSearch(true, e.target.value);
});

unmonitoredSearchInput?.addEventListener("input", (e) => {
  handleSearch(false, e.target.value);
});

// 加载链信息
async function loadChainIds() {
  try {
    const response = await fetch(`${API_BASE}/pendle/chain-ids`);
    if (response.ok) {
      const data = await response.json();
      chainMap = {};
      data.chains?.forEach(chain => {
        chainMap[chain.id] = {
          name: chain.name,
          token_address: chain.token_address,
        };
      });
      console.log(`加载了 ${Object.keys(chainMap).length} 条链信息:`, chainMap);
    } else {
      console.error(`加载链信息失败: ${response.status} ${response.statusText}`);
    }
  } catch (error) {
    console.error("加载链信息失败:", error);
  }
}

// 加载同步时间
async function loadLastSyncTime() {
  try {
    const response = await fetch(`${API_BASE}/pendle/projects/last-sync`);
    if (response.ok) {
      const data = await response.json();
      const lastSyncTimeEl = document.querySelector("#last-sync-time");
      if (lastSyncTimeEl) {
        if (data.last_sync_time) {
          const syncTime = new Date(data.last_sync_time);
          lastSyncTimeEl.textContent = `上次同步: ${formatDate(data.last_sync_time)}`;
        } else {
          lastSyncTimeEl.textContent = "未同步";
        }
      }
    }
  } catch (error) {
    console.error("加载同步时间失败:", error);
  }
}

// 格式化数字（添加千分位和单位）
function formatNumber(value, unit = "") {
  if (value === null || value === undefined) return "-";
  if (typeof value !== "number") return value;
  
  if (value >= 1000000000) {
    return `${(value / 1000000000).toFixed(2)}B${unit}`;
  } else if (value >= 1000000) {
    return `${(value / 1000000).toFixed(2)}M${unit}`;
  } else if (value >= 1000) {
    return `${(value / 1000).toFixed(2)}K${unit}`;
  } else {
    return `${value.toFixed(2)}${unit}`;
  }
}

// 格式化百分比
function formatPercent(value) {
  if (value === null || value === undefined) return "-";
  if (typeof value !== "number") return value;
  return `${value.toFixed(2)}%`;
}

// 格式化 YT 数量（智能显示，处理非常小的值）
function formatYTAmount(ytAmount, ytAmountRaw) {
  if (ytAmount === null || ytAmount === undefined) return "0.000000";
  const amount = parseFloat(ytAmount);
  if (isNaN(amount)) return "0.000000";
  
  // 如果值为 0，直接返回
  if (amount === 0) return "0.000000";
  
  // 如果值非常小（小于 0.000001），使用科学计数法或显示更多小数位
  if (amount > 0 && amount < 0.000001) {
    // 尝试使用科学计数法
    return amount.toExponential(6);
  }
  
  // 如果值大于等于 0.000001，使用常规格式化（保留足够的小数位）
  // 找到第一个非零小数位
  if (amount < 1) {
    // 对于小于1的值，保留更多小数位
    const str = amount.toString();
    const match = str.match(/\.0*[1-9]/);
    if (match) {
      // 找到第一个非零数字的位置
      const firstNonZeroIndex = match[0].length - 1;
      // 保留到第一个非零数字后6位
      return amount.toFixed(firstNonZeroIndex + 6);
    }
  }
  
  // 默认保留6位小数
  return amount.toFixed(6);
}

// 加载历史记录
async function fetchHistory() {
  if (!historyList) return;
  
  historyList.innerHTML = "<p class='loading'>加载中...</p>";
  
  try {
    const response = await fetch(`${API_BASE}/pendle/projects/history?limit=30`);
    if (!response.ok) {
      throw new Error(`HTTP error! status: ${response.status}`);
    }
    
    const data = await response.json();
    if (data.success) {
      renderHistory(data.history);
    } else {
      historyList.innerHTML = "<p class='error'>加载历史记录失败</p>";
    }
  } catch (error) {
    console.error("加载历史记录失败:", error);
    historyList.innerHTML = "<p class='error'>加载历史记录失败: " + escapeHtml(error.message) + "</p>";
  }
}

// 渲染历史记录
function renderHistory(history) {
  if (!historyList) return;
  
  if (!history || history.length === 0) {
    historyList.innerHTML = "<p class='empty-state'>暂无历史记录</p>";
    return;
  }
  
  let html = "";
  
  for (const dayHistory of history) {
    // 解析日期字符串（格式：YYYY-MM-DD）
    const dateParts = dayHistory.date.split("-");
    const year = dateParts[0];
    const month = dateParts[1];
    const day = dateParts[2];
    // 格式化为：2025年11/24
    const dateStr = `${year}年${month}/${day}`;
    
    html += `<div class="history-day">`;
    html += `<h3 class="history-day-title">${dateStr}</h3>`;
    
    if (dayHistory.added && dayHistory.added.length > 0) {
      html += `<div class="history-section">`;
      html += `<span class="history-label added">新增:</span>`;
      html += `<div class="history-projects-list">`;
      html += dayHistory.added.map(p => {
        const chainName = p.chain_id && chainMap[p.chain_id] ? chainMap[p.chain_id].name : "";
        const chainParam = chainName ? `&chain=${escapeHtml(chainName)}` : "";
        const url = `https://app.pendle.finance/trade/markets/${escapeHtml(p.address)}/swap?view=yt${chainParam}`;
        return `<a href="${url}" target="_blank" class="history-project-link">${escapeHtml(p.name)}</a>`;
      }).join("");
      html += `</div>`;
      html += `</div>`;
    }
    
    if (dayHistory.deleted && dayHistory.deleted.length > 0) {
      html += `<div class="history-section">`;
      html += `<span class="history-label deleted">删除:</span>`;
      html += `<div class="history-projects-list">`;
      html += dayHistory.deleted.map(p => {
        const chainName = p.chain_id && chainMap[p.chain_id] ? chainMap[p.chain_id].name : "";
        const chainParam = chainName ? `&chain=${escapeHtml(chainName)}` : "";
        const url = `https://app.pendle.finance/trade/markets/${escapeHtml(p.address)}/swap?view=yt${chainParam}`;
        return `<a href="${url}" target="_blank" class="history-project-link">${escapeHtml(p.name)}</a>`;
      }).join("");
      html += `</div>`;
      html += `</div>`;
    }
    
    if ((!dayHistory.added || dayHistory.added.length === 0) && 
        (!dayHistory.deleted || dayHistory.deleted.length === 0)) {
      html += `<div class="history-section">`;
      html += `<span class="history-empty">无变化</span>`;
      html += `</div>`;
    }
    
    html += `</div>`;
  }
  
  historyList.innerHTML = html;
}

// 绑定刷新历史记录按钮
if (reloadHistoryButton) {
  reloadHistoryButton.addEventListener("click", () => {
    fetchHistory();
  });
}

// 计算分组汇总
function calculateGroupSummary(projects) {
  let totalTvl = 0;
  let totalVolume24h = 0;
  let totalApy = 0;
  let apyCount = 0;
  
  projects.forEach(project => {
    if (project.tvl) totalTvl += project.tvl;
    if (project.trading_volume_24h) totalVolume24h += project.trading_volume_24h;
    if (project.implied_apy !== null && project.implied_apy !== undefined) {
      totalApy += project.implied_apy;
      apyCount++;
    }
  });
  
  return {
    tvl: totalTvl,
    volume24h: totalVolume24h,
    apy: apyCount > 0 ? totalApy / apyCount : null,  // 平均值
  };
}

// ==================== 聪明钱功能 ====================

// 获取聪明钱列表
async function fetchSmartMoney() {
  if (!smartMoneyList) return;
  
  // 保存当前展开状态
  const expandedWallets = new Set();
  smartMoneyList.querySelectorAll(".smart-money-operations").forEach(div => {
    if (div.style.display !== "none") {
      expandedWallets.add(div.id.replace("operations-", ""));
    }
  });
  
  smartMoneyList.innerHTML = "<p class='loading'>加载中...</p>";
  
  try {
    const response = await fetch(`${API_BASE}/smart-money`);
    if (!response.ok) throw new Error("获取聪明钱列表失败");
    
    const data = await response.json();
    renderSmartMoney(data.smart_money || [], expandedWallets);
  } catch (error) {
    console.error("加载聪明钱列表失败:", error);
    smartMoneyList.innerHTML = "<p class='error'>加载失败: " + escapeHtml(error.message) + "</p>";
  }
}

// 渲染聪明钱列表
function renderSmartMoney(smartMoneyArray, expandedWallets = new Set()) {
  const container = document.querySelector("#smart-money-list");
  if (!container) return;
  
  if (smartMoneyArray.length === 0) {
    container.innerHTML = "<p class='empty-state'>暂无聪明钱记录</p>";
    return;
  }
  
  let html = "";
  
  for (const item of smartMoneyArray) {
    const levelClass = item.level === "重点" ? "level-important" : 
                      item.level === "聪明钱" ? "level-smart" : "level-ant";
    const levelBadge = `<span class="smart-money-level ${levelClass}">${escapeHtml(item.level)}</span>`;
    const walletAddressEscaped = escapeHtml(item.wallet_address);
    const isExpanded = expandedWallets.has(item.wallet_address);
    
    html += `<div class="smart-money-item" data-wallet="${walletAddressEscaped}">`;
    html += `<div class="smart-money-header" data-wallet="${walletAddressEscaped}">`;
    html += `<div class="smart-money-info">`;
    html += `<span class="smart-money-name">${escapeHtml(item.name || "未命名")}</span>`;
    html += `${levelBadge}`;
    html += `<span class="smart-money-address"><a href="https://app.pendle.finance/trade/dashboard/user/${walletAddressEscaped}" target="_blank">${walletAddressEscaped}</a></span>`;
    html += `</div>`;
    html += `<div class="smart-money-item-actions">`;
    html += `<button class="btn-icon refresh-btn" data-wallet="${walletAddressEscaped}" title="刷新历史记录">🔄</button>`;
    html += `<button class="btn-icon edit-btn" data-wallet="${walletAddressEscaped}" title="编辑">✏️</button>`;
    html += `<button class="btn-icon delete-btn" data-wallet="${walletAddressEscaped}" title="删除">🗑️</button>`;
    html += `<span class="toggle-icon">${isExpanded ? "▲" : "▼"}</span>`;
    html += `</div>`;
    html += `</div>`;
    html += `<div class="smart-money-operations" id="operations-${walletAddressEscaped}" style="display: ${isExpanded ? "block" : "none"};">`;
    html += `<p class="empty-state">暂无内容</p>`;
    html += `</div>`;
    html += `</div>`;
  }
  
  container.innerHTML = html;
  
  // 绑定事件监听器
  container.querySelectorAll(".smart-money-header").forEach(header => {
    header.addEventListener("click", (e) => {
      // 如果点击的是按钮，不触发折叠
      if (e.target.closest(".btn-icon")) {
        return;
      }
      const walletAddress = header.dataset.wallet;
      toggleSmartMoneyOperations(walletAddress);
    });
  });
  
  container.querySelectorAll(".edit-btn").forEach(btn => {
    btn.addEventListener("click", (e) => {
      e.stopPropagation();
      const walletAddress = btn.dataset.wallet;
      editSmartMoney(walletAddress);
    });
  });
  
  container.querySelectorAll(".delete-btn").forEach(btn => {
    btn.addEventListener("click", (e) => {
      e.stopPropagation();
      const walletAddress = btn.dataset.wallet;
      deleteSmartMoney(walletAddress);
    });
  });
  
  container.querySelectorAll(".refresh-btn").forEach(btn => {
    btn.addEventListener("click", (e) => {
      e.stopPropagation();
      const walletAddress = btn.dataset.wallet;
      refreshWalletOperations(walletAddress);
    });
  });
  
  // 如果之前是展开的，自动加载数据
  expandedWallets.forEach(walletAddress => {
    const operationsDiv = document.getElementById(`operations-${walletAddress}`);
    if (operationsDiv && operationsDiv.style.display !== "none") {
      loadWalletOperations(walletAddress, false);
    }
  });
}

// 切换操作记录显示/隐藏
function toggleSmartMoneyOperations(walletAddress) {
  const operationsDiv = document.getElementById(`operations-${walletAddress}`);
  if (!operationsDiv) return;
  
  const item = operationsDiv.closest(".smart-money-item");
  const toggleIcon = item.querySelector(".toggle-icon");
  
  if (operationsDiv.style.display === "none") {
    operationsDiv.style.display = "block";
    toggleIcon.textContent = "▲";
    // 从数据库加载操作记录（不请求API）
    loadWalletOperations(walletAddress, false);
  } else {
    operationsDiv.style.display = "none";
    toggleIcon.textContent = "▼";
  }
}

// 手动刷新钱包操作记录（从API获取）
async function refreshWalletOperations(walletAddress) {
  const operationsDiv = document.getElementById(`operations-${walletAddress}`);
  if (!operationsDiv) return;
  
  // 确保操作记录区域是展开的
  if (operationsDiv.style.display === "none") {
    const item = operationsDiv.closest(".smart-money-item");
    const toggleIcon = item.querySelector(".toggle-icon");
    operationsDiv.style.display = "block";
    toggleIcon.textContent = "▲";
  }
  
  // 从API刷新数据
  await loadWalletOperations(walletAddress, true);
}

// 加载钱包操作记录（流式加载，不闪烁）
async function loadWalletOperations(walletAddress, refresh = false) {
  const operationsDiv = document.getElementById(`operations-${walletAddress}`);
  if (!operationsDiv) return;
  
  // 如果正在加载，不重复加载
  if (operationsDiv.dataset.loading === "true") {
    return;
  }
  
  // 显示加载状态（不替换现有内容）
  if (!operationsDiv.dataset.loaded) {
    operationsDiv.innerHTML = "<p class='loading'>加载中...</p>";
  }
  operationsDiv.dataset.loading = "true";
  
  try {
    const url = `${API_BASE}/smart-money/${encodeURIComponent(walletAddress)}/operations?hours=72${refresh ? "&refresh=true" : ""}`;
    const response = await fetch(url);
    if (!response.ok) throw new Error("获取操作记录失败");
    
    const data = await response.json();
    
    // 合并交易记录和限价订单记录
    const allOperations = [];
    
    if (data.operations && data.operations.length > 0) {
      allOperations.push(...data.operations.map(op => ({ ...op, type: "transaction" })));
    }
    
    if (data.limit_orders && data.limit_orders.length > 0) {
      allOperations.push(...data.limit_orders.map(op => ({ ...op, type: "limit_order" })));
    }
    
    // 按时间倒序排序
    allOperations.sort((a, b) => new Date(b.timestamp) - new Date(a.timestamp));
    
    if (allOperations.length > 0) {
      // 流式渲染操作记录
      renderWalletOperations(operationsDiv, allOperations);
    } else {
      operationsDiv.innerHTML = "<p class='empty-state'>暂无内容</p>";
    }
    
    operationsDiv.dataset.loaded = "true";
  } catch (error) {
    console.error("加载操作记录失败:", error);
    operationsDiv.innerHTML = "<p class='error'>加载失败: " + escapeHtml(error.message) + "</p>";
  } finally {
    operationsDiv.dataset.loading = "false";
  }
}

// 渲染钱包操作记录
function renderWalletOperations(container, operations) {
  if (!container || !operations || operations.length === 0) {
    container.innerHTML = "<p class='empty-state'>暂无内容</p>";
    return;
  }
  
  let html = "<div class='operations-list'>";
  
  for (const op of operations) {
    // 转换时间戳为北京时间
    const timestamp = new Date(op.timestamp);
    // 使用 toLocaleString 直接转换为北京时间
    const timeStr = timestamp.toLocaleString("zh-CN", {
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
      timeZone: "Asia/Shanghai",
    });
    
    // 构建项目链接
    const chainName = op.chain_id && chainMap[op.chain_id] ? chainMap[op.chain_id].name : "";
    const chainParam = chainName ? `&chain=${escapeHtml(chainName)}` : "";
    const projectUrl = op.market_address ? `https://app.pendle.finance/trade/markets/${escapeHtml(op.market_address)}/swap?view=yt${chainParam}` : "#";
    
    // 判断是交易记录还是限价订单
    if (op.type === "limit_order") {
      // 限价订单显示逻辑
      const status = op.status;
      const orderType = op.order_type;
      
      // 状态标签
      let statusLabel = "";
      let actionClass = "";
      if (status === "FILLABLE") {
        statusLabel = "开启挂单";
        actionClass = "action-buy";
      } else if (status === "CANCELLED") {
        statusLabel = "取消挂单";
        actionClass = "action-sell";
      } else if (status === "EXPIRED") {
        statusLabel = "挂单过期";
        actionClass = "action-other";
      } else if (status === "FULLY_FILLED") {
        statusLabel = "挂单填充完成";
        actionClass = "action-buy";
      } else if (status === "EMPTY_MAKER_BALANCE") {
        statusLabel = "余额不足";
        actionClass = "action-other";
      } else {
        statusLabel = status;
        actionClass = "action-other";
      }
      
      // 买入/卖出标签
      const buySellLabel = orderType === "LONG_YIELD" ? "买入" : "卖出";
      
      // 格式化数量
      const volumeStr = op.notional_volume_usd ? op.notional_volume_usd.toFixed(2) : "0.00";
      
      // 格式化 Implied Yield
      let yieldStr = "N/A";
      if (op.implied_yield !== null && op.implied_yield !== undefined) {
        yieldStr = op.implied_yield.toFixed(2) + "%";
      }
      
      html += `<div class="operation-item ${actionClass}">`;
      html += `<div class="operation-time">${escapeHtml(timeStr)}</div>`;
      html += `<div class="operation-content">`;
      html += `<span class="operation-project"><a href="${projectUrl}" target="_blank">${escapeHtml(op.project_name)}</a></span>`;
      html += `<span class="operation-action">${statusLabel}</span>`;
      html += `<span class="operation-action">${buySellLabel}</span>`;
      html += `<span class="operation-amount">数量: <span class="amount-value">${volumeStr}</span> YT</span>`;
      html += `<span class="operation-yield">Implied Yield: <span class="yield-value">${yieldStr}</span></span>`;
      html += `</div>`;
      html += `</div>`;
    } else {
      // 交易记录显示逻辑
      // 格式化金额
      const amountStr = op.amount ? op.amount.toFixed(2) : "0.00";
      
      // 格式化 Implied Yield
      let yieldStr = "N/A";
      if (op.implied_yield !== null && op.implied_yield !== undefined) {
        yieldStr = op.implied_yield.toFixed(2) + "%";
      }
      
      // 格式化利润
      const profitStr = op.profit_usd ? op.profit_usd.toFixed(2) : "0.00";
      
      // 操作类型和标签
      let actionLabel = "";
      let actionClass = "";
      if (op.action === "buyYt") {
        actionLabel = "市价买入";
        actionClass = "action-buy";
      } else if (op.action === "sellYt") {
        actionLabel = "市价卖出";
        actionClass = "action-sell";
      } else if (op.action === "buyYtLimitOrder") {
        actionLabel = "限价买入";
        actionClass = "action-buy";
      } else if (op.action === "sellYtLimitOrder") {
        actionLabel = "限价卖出";
        actionClass = "action-sell";
      } else if (op.action === "redeemYtYield") {
        actionLabel = "领取奖励";
        actionClass = "action-reward";
      } else {
        actionLabel = op.action;
        actionClass = "action-other";
      }
      
      html += `<div class="operation-item ${actionClass}">`;
      html += `<div class="operation-time">${escapeHtml(timeStr)}</div>`;
      html += `<div class="operation-content">`;
      html += `<span class="operation-project"><a href="${projectUrl}" target="_blank">${escapeHtml(op.project_name)}</a></span>`;
      html += `<span class="operation-action">${actionLabel}</span>`;
      
      // 限价买入、限价卖出、普通买入卖出显示金额和Implied Yield
      if (op.action === "buyYt" || op.action === "sellYt" || op.action === "buyYtLimitOrder" || op.action === "sellYtLimitOrder") {
        html += `<span class="operation-amount">金额: <span class="amount-value">${amountStr}</span></span>`;
        html += `<span class="operation-yield">Implied Yield: <span class="yield-value">${yieldStr}</span></span>`;
      }
      
      // 限价买入显示利润为0
      if (op.action === "buyYtLimitOrder") {
        html += `<span class="operation-profit">利润: 0.00 USD</span>`;
      }
      
      // 卖出、限价卖出、领取奖励显示利润
      if (op.action === "sellYt" || op.action === "sellYtLimitOrder" || op.action === "redeemYtYield") {
        html += `<span class="operation-profit">利润: ${profitStr} USD</span>`;
      }
      
      html += `</div>`;
      html += `</div>`;
    }
  }
  
  html += "</div>";
  
  // 使用流式更新，不闪烁
  container.innerHTML = html;
}

// 添加聪明钱
async function addSmartMoney() {
  const walletAddress = prompt("请输入钱包地址:");
  if (!walletAddress) return;
  
  const name = prompt("请输入名称（可选）:");
  const level = prompt("请输入等级（重点/聪明钱/蚂蚁仓）:", "聪明钱");
  
  if (!["重点", "聪明钱", "蚂蚁仓"].includes(level)) {
    alert("等级必须是：重点、聪明钱或蚂蚁仓");
    return;
  }
  
  try {
    const response = await fetch(`${API_BASE}/smart-money`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        wallet_address: walletAddress.trim(),
        name: name ? name.trim() : null,
        level: level,
      }),
    });
    
    if (!response.ok) {
      const error = await response.json();
      throw new Error(error.detail || "添加失败");
    }
    
    alert("添加成功！");
    await fetchSmartMoney();
    
    // 添加成功后，自动请求历史记录并显示
    const newItem = document.querySelector(`[data-wallet="${escapeHtml(walletAddress.trim())}"]`);
    if (newItem) {
      const operationsDiv = newItem.querySelector(".smart-money-operations");
      const toggleIcon = newItem.querySelector(".toggle-icon");
      if (operationsDiv && toggleIcon) {
        operationsDiv.style.display = "block";
        toggleIcon.textContent = "▲";
        // 首次添加时从API刷新数据
        await loadWalletOperations(walletAddress.trim(), true);
      }
    }
  } catch (error) {
    console.error("添加聪明钱失败:", error);
    alert("添加失败: " + error.message);
  }
}

// 编辑聪明钱
async function editSmartMoney(walletAddress) {
  // 先获取当前数据
  try {
    const response = await fetch(`${API_BASE}/smart-money`);
    if (!response.ok) throw new Error("获取列表失败");
    
    const data = await response.json();
    const item = data.smart_money.find(sm => sm.wallet_address === walletAddress);
    
    if (!item) {
      alert("未找到该记录");
      return;
    }
    
    const name = prompt("请输入名称（可选）:", item.name || "");
    const level = prompt("请输入等级（重点/聪明钱/蚂蚁仓）:", item.level);
    
    if (!["重点", "聪明钱", "蚂蚁仓"].includes(level)) {
      alert("等级必须是：重点、聪明钱或蚂蚁仓");
      return;
    }
    
    const updateResponse = await fetch(`${API_BASE}/smart-money/${encodeURIComponent(walletAddress)}`, {
      method: "PUT",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        name: name ? name.trim() : null,
        level: level,
      }),
    });
    
    if (!updateResponse.ok) {
      const error = await updateResponse.json();
      throw new Error(error.detail || "更新失败");
    }
    
    alert("更新成功！");
    fetchSmartMoney();
  } catch (error) {
    console.error("编辑聪明钱失败:", error);
    alert("编辑失败: " + error.message);
  }
}

// 删除聪明钱
async function deleteSmartMoney(walletAddress) {
  if (!confirm("确定要删除这条记录吗？")) return;
  
  try {
    const response = await fetch(`${API_BASE}/smart-money/${encodeURIComponent(walletAddress)}`, {
      method: "DELETE",
    });
    
    if (!response.ok) {
      const error = await response.json();
      throw new Error(error.detail || "删除失败");
    }
    
    alert("删除成功！");
    fetchSmartMoney();
  } catch (error) {
    console.error("删除聪明钱失败:", error);
    alert("删除失败: " + error.message);
  }
}

// 绑定按钮事件
if (addSmartMoneyButton) {
  addSmartMoneyButton.addEventListener("click", addSmartMoney);
}

if (reloadSmartMoneyButton) {
  reloadSmartMoneyButton.addEventListener("click", fetchSmartMoney);
}

// 初始化：加载项目列表和分组
// 注意：首次加载时不自动同步，避免长时间等待
// 用户可以通过"同步项目"按钮手动触发同步
document.addEventListener("DOMContentLoaded", () => {
  console.log("页面加载完成，开始初始化");
  fetchProjects(false);  // 不自动同步，避免首次加载太慢
  loadGroups();
  loadChainIds();
  loadLastSyncTime();
  
  // 自动启动价格测试（延迟一点，确保 DOM 元素都已加载）
  setTimeout(() => {
    console.log("自动启动价格测试");
    startAutoUpdate();
  }, 500);
});
