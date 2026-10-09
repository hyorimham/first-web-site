// 페이지 로드 완료 후 실행
document.addEventListener('DOMContentLoaded', () => {

    // 1. 글 작성/수정 폼 유효성 검사 (빈 값 전송 방지)
    const postForm = document.querySelector('form');
    if (postForm) {
        postForm.addEventListener('submit', (e) => {
            const titleInput = document.querySelector('input[name="title"]');
            const contentInput = document.querySelector('textarea[name="content"]');

            if (titleInput && titleInput.value.trim() === '') {
                alert('제목을 입력해 주세요.');
                titleInput.focus();
                e.preventDefault(); // 서버 전송 막기
                return;
            }

            if (contentInput && contentInput.value.trim() === '') {
                alert('내용을 입력해 주세요.');
                contentInput.focus();
                e.preventDefault(); // 서버 전송 막기
                return;
            }
        });
    }

    // 2. 삭제 버튼 클릭 시 재확인 팝업 (실수 방지)
    const deleteButtons = document.querySelectorAll('.btn-danger');
    deleteButtons.forEach(button => {
        button.addEventListener('click', (e) => {
            if (!confirm('정말로 이 게시글을 삭제하시겠습니까?')) {
                e.preventDefault(); // 삭제 진행 취소
            }
        });
    });

});