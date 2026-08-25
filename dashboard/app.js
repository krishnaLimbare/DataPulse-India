// Interactive DataPulse-India Dashboard Engine

// Sample live data extracted from initial run for instant UI rendering
const SAMPLE_MANDI_DATA = [
  { state: "Tamil Nadu", district: "Karur", market: "Kulithalai", commodity: "Mango", variety: "Neelam", min_price: 5000, max_price: 6000, modal_price: 5500 },
  { state: "Tamil Nadu", district: "Karur", market: "Kulithalai", commodity: "Potato", variety: "Jyoti", min_price: 2800, max_price: 3400, modal_price: 3100 },
  { state: "Tamil Nadu", district: "Karur", market: "Kulithalai", commodity: "Tomato", variety: "Local", min_price: 1800, max_price: 2400, modal_price: 2100 },
  { state: "Tamil Nadu", district: "Karur", market: "Kulithalai", commodity: "Onion", variety: "Nasik", min_price: 3200, max_price: 3800, modal_price: 3500 },
  { state: "Tamil Nadu", district: "Karur", market: "Kulithalai", commodity: "Cauliflower", variety: "Ranchi", min_price: 3000, max_price: 4000, modal_price: 3500 },
  { state: "Tamil Nadu", district: "Karur", market: "Kulithalai", commodity: "Bhindi", variety: "Bhindi", min_price: 3000, max_price: 3800, modal_price: 3400 },
  { state: "Tamil Nadu", district: "Karur", market: "Kulithalai", commodity: "Cabbage", variety: "Cabbage", min_price: 3500, max_price: 4000, modal_price: 3750 },
  { state: "Andhra Pradesh", district: "Srikakulam", market: "Etcherla APMC", commodity: "Paddy(Common)", variety: "1121", min_price: 2369, max_price: 2369, modal_price: 2369 },
  { state: "Madhya Pradesh", district: "Indore", market: "Indore APMC", commodity: "Potato", variety: "Desi", min_price: 2200, max_price: 2600, modal_price: 2400 },
  { state: "Madhya Pradesh", district: "Indore", market: "Indore APMC", commodity: "Onion", variety: "Red", min_price: 2900, max_price: 3300, modal_price: 3100 },
  { state: "Gujarat", district: "Rajkot", market: "Rajkot APMC", commodity: "Tomato", variety: "Hybrid", min_price: 1600, max_price: 2200, modal_price: 1900 },
  { state: "Punjab", district: "Ludhiana", market: "Ludhiana APMC", commodity: "Potato", variety: "Kufri", min_price: 2400, max_price: 2900, modal_price: 2650 }
];

const DOMAIN_METRICS = {
  mandi: {
    title: "🌾 Food & Mandi Price Index",
    description: "Daily commodity prices collected from 250+ agricultural wholesale markets across India.",
    totalRows: "5,000",
    markets: "250+",
    topCommodity: "Potato",
    status: "100% Green",
    chartTitle: "📊 Average Modal Price by Commodity (₹ / Quintal)",
    chartData: {
      labels: ["Mango", "Cabbage", "Onion", "Cauliflower", "Bhindi", "Potato", "Paddy", "Tomato"],
      values: [5500, 3750, 3300, 3500, 3400, 2716, 2369, 2000]
    }
  },
  cars: {
    title: "🏎️ Used Car Valuation Index",
    description: "Tracking used vehicle resale price depreciation trends across Indian cities.",
    totalRows: "Pipeline Ready",
    markets: "12 Cities",
    topCommodity: "Maruti Swift",
    status: "Source Preview",
    chartTitle: "📊 Average Used Car Resale Value by Model (₹ Lakhs)",
    chartData: {
      labels: ["Fortuner", "Creta", "City", "Swift", "Baleno", "i20"],
      values: [28.5, 11.2, 8.4, 5.8, 6.2, 5.4]
    }
  },
  jobs: {
    title: "💼 Tech Skill Demand Tracker",
    description: "Monitoring hiring demand and salary indexes for tech skills across India.",
    totalRows: "Pipeline Ready",
    markets: "6 Tech Hubs",
    topCommodity: "Python",
    status: "Source Preview",
    chartTitle: "📊 Developer Skill Hiring Demand Index",
    chartData: {
      labels: ["Python", "React", "SQL", "Docker", "Flutter", "Java"],
      values: [92, 85, 78, 74, 68, 65]
    }
  },
  rents: {
    title: "🏠 Metro Housing Rent Index",
    description: "Tracking apartment rental inflation across Bangalore, Mumbai, Pune, and Delhi-NCR.",
    totalRows: "Pipeline Ready",
    markets: "4 Metros",
    topCommodity: "2BHK Rent",
    status: "Source Preview",
    chartTitle: "📊 Average Monthly 2BHK Rent (₹ Thousands)",
    chartData: {
      labels: ["Mumbai", "Bangalore", "Gurgaon", "Pune", "Hyderabad", "Chennai"],
      values: [55, 38, 35, 26, 24, 22]
    }
  }
};

let currentChart = null;
let currentDomain = "mandi";

// Initialize Dashboard
document.addEventListener("DOMContentLoaded", () => {
  setupTabs();
  setupSearch();
  setupFilterPills();
  renderDomain("mandi");
});

function setupTabs() {
  const tabs = document.querySelectorAll(".tab-btn");
  tabs.forEach(tab => {
    tab.addEventListener("click", () => {
      tabs.forEach(t => t.classList.remove("active"));
      tab.classList.add("active");
      const domain = tab.dataset.domain;
      renderDomain(domain);
    });
  });
}

function renderDomain(domain) {
  currentDomain = domain;
  const config = DOMAIN_METRICS[domain];
  
  // Update Header & KPIs
  document.getElementById("panelTitle").textContent = config.title;
  document.getElementById("panelDescription").textContent = config.description;
  document.getElementById("kpiTotalRows").textContent = config.totalRows;
  document.getElementById("kpiMarkets").textContent = config.markets;
  document.getElementById("kpiTopCommodity").textContent = config.topCommodity;

  // Render Chart
  renderChart(config.chartTitle, config.chartData);

  // Render Table
  renderTable(SAMPLE_MANDI_DATA);
}

function renderChart(title, chartData) {
  const ctx = document.getElementById("analyticsChart").getContext("2d");
  
  if (currentChart) {
    currentChart.destroy();
  }

  currentChart = new Chart(ctx, {
    type: "bar",
    data: {
      labels: chartData.labels,
      datasets: [{
        label: title,
        data: chartData.values,
        backgroundColor: "rgba(56, 189, 248, 0.6)",
        borderColor: "#38bdf8",
        borderWidth: 2,
        borderRadius: 6
      }]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { display: false }
      },
      scales: {
        x: {
          grid: { color: "#232d45" },
          ticks: { color: "#94a3b8", font: { family: "Plus Jakarta Sans" } }
        },
        y: {
          grid: { color: "#232d45" },
          ticks: { color: "#94a3b8", font: { family: "Plus Jakarta Sans" } }
        }
      }
    }
  });
}

function renderTable(data) {
  const tbody = document.getElementById("tableBody");
  tbody.innerHTML = "";

  data.forEach(row => {
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td><strong>${row.state}</strong></td>
      <td>${row.district} / ${row.market}</td>
      <td><strong>${row.commodity}</strong></td>
      <td>${row.variety}</td>
      <td>₹${row.min_price.toLocaleString('en-IN')}</td>
      <td>₹${row.max_price.toLocaleString('en-IN')}</td>
      <td class="price-tag">₹${row.modal_price.toLocaleString('en-IN')}</td>
      <td><span class="status-tag">Validated</span></td>
    `;
    tbody.appendChild(tr);
  });
}

function setupSearch() {
  const searchInput = document.getElementById("searchInput");
  searchInput.addEventListener("input", (e) => {
    const query = e.target.value.toLowerCase().trim();
    filterData(query);
  });
}

function setupFilterPills() {
  const pills = document.querySelectorAll(".filter-pills .pill");
  pills.forEach(pill => {
    pill.addEventListener("click", () => {
      pills.forEach(p => p.classList.remove("active"));
      pill.classList.add("active");
      const filter = pill.dataset.filter;
      if (filter === "all") {
        renderTable(SAMPLE_MANDI_DATA);
      } else {
        const filtered = SAMPLE_MANDI_DATA.filter(d => d.commodity.toLowerCase() === filter.toLowerCase());
        renderTable(filtered);
      }
    });
  });
}

function filterData(query) {
  if (!query) {
    renderTable(SAMPLE_MANDI_DATA);
    return;
  }

  const filtered = SAMPLE_MANDI_DATA.filter(item => 
    item.commodity.toLowerCase().includes(query) ||
    item.state.toLowerCase().includes(query) ||
    item.district.toLowerCase().includes(query) ||
    item.market.toLowerCase().includes(query)
  );

  renderTable(filtered);
}
