import './App.css'

const sections = ['Company overview', 'System design', 'Promotion demo', 'Sources']

function App() {
  return (
    <main className="workspace">
      <header><span className="brand">General Mills / Project</span><span className="badge">Project starter</span></header>
      <section className="intro">
        <p className="eyebrow">SUPPLIER PROMOTION MANAGEMENT</p>
        <h1>A fresh start.<br />Ready to build.</h1>
        <p className="description">General Mills 프로모션 관리 프로젝트의 기본 작업 공간입니다.<br />자료가 준비되면 기업 분석, 시스템 구성, 데모를 추가할 수 있어요.</p>
      </section>
      <section className="sections" aria-label="프로젝트 구성">
        {sections.map((title, index) => (
          <article key={title}><span className="number">0{index + 1}</span><h2>{title}</h2><p>자료 준비 중</p></article>
        ))}
      </section>
      <footer>Independent academic project · 초기 화면 / 실제 기업 데이터 미연결</footer>
    </main>
  )
}

export default App
