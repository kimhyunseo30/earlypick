import {Link} from 'react-router-dom';

type ProductCardProps = {
    id:number;
    name: string;
    trendScore: number;
    prediction : string;
    recommendation: string;
};

function ProductCard({
    id,
    name,
    trendScore,
    prediction,
    recommendation,
}:ProductCardProps){
    return(
        <article className='card product-card'>
            <div className='product-card_top'>
                <h3>{name}</h3>
                <span className='badge'>트렌드 {trendScore}</span>
            </div>

            <p className='muted'>예측: {prediction}</p>
            <p className='muted'>추천: {recommendation}</p>

            <Link to={`/products/${id}`} className='button'>
            상세보기
            </Link>

        </article>
    );
}

export default ProductCard;